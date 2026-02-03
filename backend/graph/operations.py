"""Knowledge graph CRUD operations."""

import uuid
from datetime import datetime
from typing import Optional

from backend.core.database import neo4j_session
from backend.graph.schema import EntityType, RelationshipType, GRAPH_SCHEMA


class CampaignGraphOps:
    """Operations for the campaign knowledge graph."""

    def __init__(self):
        """Initialize and ensure schema exists."""
        self._ensure_schema()

    def _ensure_schema(self):
        """Create constraints and indexes if they don't exist."""
        with neo4j_session() as session:
            for constraint in GRAPH_SCHEMA["constraints"]:
                try:
                    session.run(constraint)
                except Exception:
                    pass  # Constraint may already exist

            for index in GRAPH_SCHEMA["indexes"]:
                try:
                    session.run(index)
                except Exception:
                    pass  # Index may already exist

    def create_entity(
        self,
        name: str,
        entity_type: str | EntityType,
        description: Optional[str] = None,
        properties: Optional[dict] = None,
        entity_id: Optional[str] = None,
    ) -> dict:
        """Create a new entity in the graph.

        Args:
            name: Entity name
            entity_type: Type of entity (PC, NPC, LOCATION, etc.)
            description: Optional description
            properties: Additional properties
            entity_id: Optional custom ID (auto-generated if not provided)

        Returns:
            Created entity as dict
        """
        if isinstance(entity_type, EntityType):
            entity_type = entity_type.value

        entity_id = entity_id or str(uuid.uuid4())
        props = properties or {}
        now = datetime.utcnow().isoformat()

        query = """
        CREATE (e:Entity {
            id: $id,
            name: $name,
            entity_type: $entity_type,
            description: $description,
            created_at: $created_at,
            updated_at: $updated_at
        })
        SET e += $properties
        RETURN e
        """

        with neo4j_session() as session:
            result = session.run(
                query,
                id=entity_id,
                name=name,
                entity_type=entity_type,
                description=description,
                created_at=now,
                updated_at=now,
                properties=props,
            )
            record = result.single()
            return dict(record["e"]) if record else None

    def get_entity(self, entity_id: str) -> Optional[dict]:
        """Get an entity by ID.

        Args:
            entity_id: The entity's unique ID

        Returns:
            Entity as dict or None if not found
        """
        query = """
        MATCH (e:Entity {id: $id})
        RETURN e
        """

        with neo4j_session() as session:
            result = session.run(query, id=entity_id)
            record = result.single()
            return dict(record["e"]) if record else None

    def update_entity(
        self,
        entity_id: str,
        updates: dict,
    ) -> Optional[dict]:
        """Update an entity's properties.

        Args:
            entity_id: The entity's unique ID
            updates: Properties to update

        Returns:
            Updated entity as dict or None if not found
        """
        updates["updated_at"] = datetime.utcnow().isoformat()

        query = """
        MATCH (e:Entity {id: $id})
        SET e += $updates
        RETURN e
        """

        with neo4j_session() as session:
            result = session.run(query, id=entity_id, updates=updates)
            record = result.single()
            return dict(record["e"]) if record else None

    def delete_entity(self, entity_id: str) -> bool:
        """Delete an entity and its relationships.

        Args:
            entity_id: The entity's unique ID

        Returns:
            True if deleted, False if not found
        """
        query = """
        MATCH (e:Entity {id: $id})
        DETACH DELETE e
        RETURN count(e) as deleted
        """

        with neo4j_session() as session:
            result = session.run(query, id=entity_id)
            record = result.single()
            return record["deleted"] > 0 if record else False

    def list_entities(
        self,
        entity_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List entities, optionally filtered by type.

        Args:
            entity_type: Filter by entity type
            limit: Maximum number of results

        Returns:
            List of entities as dicts
        """
        if entity_type:
            query = """
            MATCH (e:Entity {entity_type: $entity_type})
            RETURN e
            ORDER BY e.name
            LIMIT $limit
            """
            params = {"entity_type": entity_type, "limit": limit}
        else:
            query = """
            MATCH (e:Entity)
            RETURN e
            ORDER BY e.name
            LIMIT $limit
            """
            params = {"limit": limit}

        with neo4j_session() as session:
            result = session.run(query, **params)
            return [dict(record["e"]) for record in result]

    def create_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str | RelationshipType,
        properties: Optional[dict] = None,
    ) -> Optional[dict]:
        """Create a relationship between two entities.

        Args:
            source_id: Source entity ID
            target_id: Target entity ID
            relationship_type: Type of relationship
            properties: Additional relationship properties

        Returns:
            Relationship info as dict or None if entities not found
        """
        if isinstance(relationship_type, RelationshipType):
            relationship_type = relationship_type.value

        props = properties or {}
        props["created_at"] = datetime.utcnow().isoformat()

        # Use APOC or dynamic relationship creation
        query = f"""
        MATCH (source:Entity {{id: $source_id}})
        MATCH (target:Entity {{id: $target_id}})
        MERGE (source)-[r:{relationship_type}]->(target)
        SET r += $properties
        RETURN source.id as source, target.id as target, type(r) as type
        """

        with neo4j_session() as session:
            result = session.run(
                query,
                source_id=source_id,
                target_id=target_id,
                properties=props,
            )
            record = result.single()
            if record:
                return {
                    "source_id": record["source"],
                    "target_id": record["target"],
                    "relationship_type": record["type"],
                }
            return None

    def get_neighbors(
        self,
        entity_id: str,
        max_hops: int = 1,
        relationship_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """Get neighboring entities within N hops.

        Args:
            entity_id: Starting entity ID
            max_hops: Maximum relationship hops
            relationship_types: Filter by relationship types

        Returns:
            List of neighbor entities with relationship info
        """
        if relationship_types:
            rel_filter = "|".join(relationship_types)
            query = f"""
            MATCH (start:Entity {{id: $id}})
            MATCH path = (start)-[r:{rel_filter}*1..{max_hops}]-(neighbor:Entity)
            RETURN DISTINCT neighbor,
                   [rel in relationships(path) | type(rel)] as relationship_types,
                   length(path) as distance
            ORDER BY distance
            """
        else:
            query = f"""
            MATCH (start:Entity {{id: $id}})
            MATCH path = (start)-[*1..{max_hops}]-(neighbor:Entity)
            RETURN DISTINCT neighbor,
                   [rel in relationships(path) | type(rel)] as relationship_types,
                   length(path) as distance
            ORDER BY distance
            """

        with neo4j_session() as session:
            result = session.run(query, id=entity_id)
            return [
                {
                    **dict(record["neighbor"]),
                    "relationship_types": record["relationship_types"],
                    "distance": record["distance"],
                }
                for record in result
            ]

    def search(
        self,
        query: str,
        entity_types: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search entities by name or description.

        Args:
            query: Search query
            entity_types: Filter by entity types
            limit: Maximum results

        Returns:
            Matching entities
        """
        # Use CONTAINS for simple substring matching
        # (fulltext index would be better for production)
        if entity_types:
            cypher = """
            MATCH (e:Entity)
            WHERE e.entity_type IN $types
              AND (toLower(e.name) CONTAINS toLower($query)
                   OR toLower(e.description) CONTAINS toLower($query))
            RETURN e
            ORDER BY CASE WHEN toLower(e.name) STARTS WITH toLower($query) THEN 0 ELSE 1 END
            LIMIT $limit
            """
            params = {"query": query, "types": entity_types, "limit": limit}
        else:
            cypher = """
            MATCH (e:Entity)
            WHERE toLower(e.name) CONTAINS toLower($query)
               OR toLower(e.description) CONTAINS toLower($query)
            RETURN e
            ORDER BY CASE WHEN toLower(e.name) STARTS WITH toLower($query) THEN 0 ELSE 1 END
            LIMIT $limit
            """
            params = {"query": query, "limit": limit}

        with neo4j_session() as session:
            result = session.run(cypher, **params)
            return [dict(record["e"]) for record in result]

    def get_entity_context(
        self,
        entity_id: str,
        max_hops: int = 2,
    ) -> dict:
        """Get an entity with its full context (neighbors, relationships).

        Useful for RAG context building.

        Args:
            entity_id: Entity ID
            max_hops: How far to traverse

        Returns:
            Entity with its context
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return None

        neighbors = self.get_neighbors(entity_id, max_hops=max_hops)

        return {
            "entity": entity,
            "neighbors": neighbors,
            "total_connections": len(neighbors),
        }

    def get_campaign_summary(self) -> dict:
        """Get a summary of the campaign knowledge graph.

        Returns:
            Summary statistics
        """
        query = """
        MATCH (e:Entity)
        RETURN e.entity_type as type, count(*) as count
        ORDER BY count DESC
        """

        with neo4j_session() as session:
            result = session.run(query)
            type_counts = {record["type"]: record["count"] for record in result}

        rel_query = """
        MATCH ()-[r]->()
        RETURN type(r) as type, count(*) as count
        ORDER BY count DESC
        """

        with neo4j_session() as session:
            result = session.run(rel_query)
            rel_counts = {record["type"]: record["count"] for record in result}

        return {
            "entity_counts": type_counts,
            "relationship_counts": rel_counts,
            "total_entities": sum(type_counts.values()),
            "total_relationships": sum(rel_counts.values()),
        }

    def get_full_graph(
        self,
        entity_types: Optional[list[str]] = None,
        limit: int = 200,
    ) -> dict:
        """Get the full graph data for visualization.

        Args:
            entity_types: Optional filter by entity types.
            limit: Maximum number of nodes.

        Returns:
            Dict with nodes and links for graph visualization.
        """
        # Get all nodes
        if entity_types:
            node_query = """
            MATCH (e:Entity)
            WHERE e.entity_type IN $types
            RETURN e
            LIMIT $limit
            """
            params = {"types": entity_types, "limit": limit}
        else:
            node_query = """
            MATCH (e:Entity)
            RETURN e
            LIMIT $limit
            """
            params = {"limit": limit}

        with neo4j_session() as session:
            result = session.run(node_query, **params)
            nodes = [dict(record["e"]) for record in result]

        # Get node IDs for filtering relationships
        node_ids = {n["id"] for n in nodes}

        # Get all relationships between these nodes
        link_query = """
        MATCH (source:Entity)-[r]->(target:Entity)
        WHERE source.id IN $node_ids AND target.id IN $node_ids
        RETURN source.id as source, target.id as target, type(r) as type,
               properties(r) as properties
        """

        with neo4j_session() as session:
            result = session.run(link_query, node_ids=list(node_ids))
            links = [
                {
                    "source": record["source"],
                    "target": record["target"],
                    "type": record["type"],
                    "properties": record["properties"],
                }
                for record in result
            ]

        return {
            "nodes": nodes,
            "links": links,
            "node_count": len(nodes),
            "link_count": len(links),
        }

    # ===================
    # Player Operations
    # ===================

    def create_player(
        self,
        name: str,
        email: Optional[str] = None,
        discord_id: Optional[str] = None,
        player_id: Optional[str] = None,
    ) -> dict:
        """Create a new player entity.

        Args:
            name: Player's name.
            email: Optional email address.
            discord_id: Optional Discord ID.
            player_id: Optional custom ID.

        Returns:
            Created player entity.
        """
        return self.create_entity(
            name=name,
            entity_type=EntityType.PLAYER,
            entity_id=player_id or f"player_{name.lower().replace(' ', '_')}",
            properties={
                "email": email,
                "discord_id": discord_id,
                "joined_at": datetime.utcnow().isoformat(),
            },
        )

    def get_player(self, player_id: str) -> Optional[dict]:
        """Get a player by ID with their characters.

        Args:
            player_id: Player's ID.

        Returns:
            Player entity with characters, or None.
        """
        player = self.get_entity(player_id)
        if not player:
            return None

        # Get player's characters
        characters = self.get_player_characters(player_id)
        player["characters"] = characters

        # Get active PC if set
        active_pc_id = player.get("active_pc_id")
        if active_pc_id:
            player["active_pc"] = next(
                (c for c in characters if c["id"] == active_pc_id), None
            )
        else:
            player["active_pc"] = characters[0] if characters else None

        return player

    def list_players(self, campaign_id: Optional[str] = None) -> list[dict]:
        """List all players, optionally filtered by campaign.

        Args:
            campaign_id: Optional campaign to filter by.

        Returns:
            List of player entities.
        """
        if campaign_id:
            query = """
            MATCH (p:Entity {entity_type: 'PLAYER'})-[:BELONGS_TO]->(c:Entity {id: $campaign_id})
            RETURN p
            ORDER BY p.name
            """
            with neo4j_session() as session:
                result = session.run(query, campaign_id=campaign_id)
                return [dict(record["p"]) for record in result]
        else:
            return self.list_entities(entity_type="PLAYER")

    def add_player_to_campaign(self, player_id: str, campaign_id: str) -> dict:
        """Add a player to a campaign.

        Args:
            player_id: Player's ID.
            campaign_id: Campaign's ID.

        Returns:
            Relationship info.
        """
        return self.create_relationship(
            source_id=player_id,
            target_id=campaign_id,
            relationship_type=RelationshipType.BELONGS_TO,
        )

    def get_campaign_players(self, campaign_id: str) -> list[dict]:
        """Get all players in a campaign with their active characters.

        Args:
            campaign_id: Campaign's ID.

        Returns:
            List of players with character info.
        """
        query = """
        MATCH (p:Entity {entity_type: 'PLAYER'})-[:BELONGS_TO]->(c:Entity {id: $campaign_id})
        OPTIONAL MATCH (p)-[:PLAYS_AS]->(pc:Entity {entity_type: 'PC'})
        RETURN p, collect(pc) as characters
        ORDER BY p.name
        """
        with neo4j_session() as session:
            result = session.run(query, campaign_id=campaign_id)
            players = []
            for record in result:
                player = dict(record["p"])
                characters = [dict(c) for c in record["characters"] if c]
                player["characters"] = characters
                # Set active PC
                active_pc_id = player.get("active_pc_id")
                if active_pc_id:
                    player["active_pc"] = next(
                        (c for c in characters if c["id"] == active_pc_id), None
                    )
                else:
                    player["active_pc"] = characters[0] if characters else None
                players.append(player)
            return players

    def link_player_character(self, player_id: str, pc_id: str) -> dict:
        """Link a player to a character (PC).

        Args:
            player_id: Player's ID.
            pc_id: Character's ID.

        Returns:
            Relationship info.
        """
        # Create PLAYS_AS relationship
        rel = self.create_relationship(
            source_id=player_id,
            target_id=pc_id,
            relationship_type=RelationshipType.PLAYS_AS,
        )

        # Update PC with player reference
        self.update_entity(pc_id, {"player_id": player_id})

        return rel

    def get_player_characters(self, player_id: str) -> list[dict]:
        """Get all characters (PCs) for a player.

        Args:
            player_id: Player's ID.

        Returns:
            List of PC entities.
        """
        query = """
        MATCH (p:Entity {id: $player_id})-[:PLAYS_AS]->(pc:Entity {entity_type: 'PC'})
        RETURN pc
        ORDER BY pc.name
        """
        with neo4j_session() as session:
            result = session.run(query, player_id=player_id)
            return [dict(record["pc"]) for record in result]

    def set_active_character(self, player_id: str, pc_id: str) -> dict:
        """Set the active character for a player.

        Args:
            player_id: Player's ID.
            pc_id: Character's ID to set as active.

        Returns:
            Updated player entity.
        """
        self.update_entity(player_id, {"active_pc_id": pc_id})
        return self.get_player(player_id)

    def create_player_character(
        self,
        player_id: str,
        name: str,
        character_class: str,
        level: int = 1,
        race: Optional[str] = None,
        hp: Optional[int] = None,
        max_hp: Optional[int] = None,
        initiative_bonus: int = 0,
        description: Optional[str] = None,
    ) -> dict:
        """Create a new character for a player.

        Args:
            player_id: Player's ID.
            name: Character name.
            character_class: D&D class.
            level: Character level.
            race: Character race.
            hp: Current HP.
            max_hp: Maximum HP.
            initiative_bonus: Initiative modifier.
            description: Character description.

        Returns:
            Created PC entity.
        """
        # Get player name for denormalization
        player = self.get_entity(player_id)
        player_name = player["name"] if player else None

        pc = self.create_entity(
            name=name,
            entity_type=EntityType.PC,
            description=description,
            properties={
                "player_id": player_id,
                "player_name": player_name,
                "class": character_class,
                "level": level,
                "race": race,
                "hp": hp or (level * 8),  # Default HP calculation
                "max_hp": max_hp or (level * 8),
                "initiative_bonus": initiative_bonus,
                "status": "alive",
            },
        )

        # Link player to character
        self.link_player_character(player_id, pc["id"])

        # Set as active if first character
        existing_chars = self.get_player_characters(player_id)
        if len(existing_chars) == 1:
            self.set_active_character(player_id, pc["id"])

        return pc

    # ===================
    # Session Operations
    # ===================

    def record_session_attendance(
        self,
        session_id: str,
        player_ids: list[str],
        character_ids: Optional[list[str]] = None,
    ) -> dict:
        """Record which players attended a session.

        Args:
            session_id: Session's ID.
            player_ids: List of player IDs who attended.
            character_ids: Optional list of which character each player used.

        Returns:
            Summary of attendance recorded.
        """
        recorded = []
        for i, player_id in enumerate(player_ids):
            # Create attendance relationship
            self.create_relationship(
                source_id=player_id,
                target_id=session_id,
                relationship_type=RelationshipType.ATTENDED,
            )

            # If character specified, record participation
            if character_ids and i < len(character_ids) and character_ids[i]:
                self.create_relationship(
                    source_id=character_ids[i],
                    target_id=session_id,
                    relationship_type=RelationshipType.PARTICIPATED_IN,
                )

            recorded.append(player_id)

        return {
            "session_id": session_id,
            "players_recorded": len(recorded),
            "player_ids": recorded,
        }

    def get_session_attendees(self, session_id: str) -> list[dict]:
        """Get all players who attended a session with their characters.

        Args:
            session_id: Session's ID.

        Returns:
            List of players with the character they used.
        """
        query = """
        MATCH (p:Entity {entity_type: 'PLAYER'})-[:ATTENDED]->(s:Entity {id: $session_id})
        OPTIONAL MATCH (pc:Entity {entity_type: 'PC'})-[:PARTICIPATED_IN]->(s)
        WHERE (p)-[:PLAYS_AS]->(pc)
        RETURN p, pc
        ORDER BY p.name
        """
        with neo4j_session() as session:
            result = session.run(query, session_id=session_id)
            attendees = []
            for record in result:
                player = dict(record["p"])
                if record["pc"]:
                    player["character_used"] = dict(record["pc"])
                else:
                    # Fall back to active character
                    player["character_used"] = None
                attendees.append(player)
            return attendees

    def create_campaign(
        self,
        name: str,
        setting: Optional[str] = None,
        description: Optional[str] = None,
        campaign_id: Optional[str] = None,
    ) -> dict:
        """Create a new campaign.

        Args:
            name: Campaign name.
            setting: Campaign setting (e.g., "Forgotten Realms").
            description: Campaign description.
            campaign_id: Optional custom ID.

        Returns:
            Created campaign entity.
        """
        return self.create_entity(
            name=name,
            entity_type=EntityType.CAMPAIGN,
            description=description,
            entity_id=campaign_id or f"campaign_{name.lower().replace(' ', '_')}",
            properties={
                "setting": setting,
                "start_date": datetime.utcnow().isoformat(),
                "status": "active",
            },
        )

    def create_session(
        self,
        campaign_id: str,
        session_number: int,
        name: Optional[str] = None,
        date: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> dict:
        """Create a new session for a campaign.

        Args:
            campaign_id: Campaign's ID.
            session_number: Session number.
            name: Optional session name/title.
            date: Session date.
            summary: Session summary.

        Returns:
            Created session entity.
        """
        session_name = name or f"Session {session_number}"
        session = self.create_entity(
            name=session_name,
            entity_type=EntityType.SESSION,
            description=summary,
            entity_id=f"{campaign_id}_session_{session_number}",
            properties={
                "campaign_id": campaign_id,
                "session_number": session_number,
                "date": date or datetime.utcnow().isoformat(),
            },
        )

        # Link session to campaign
        self.create_relationship(
            source_id=session["id"],
            target_id=campaign_id,
            relationship_type=RelationshipType.BELONGS_TO,
        )

        return session
