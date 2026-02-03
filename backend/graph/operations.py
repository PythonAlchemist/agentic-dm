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
