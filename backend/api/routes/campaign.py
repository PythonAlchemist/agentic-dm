"""Campaign management endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.graph.operations import CampaignGraphOps

router = APIRouter()

_graph_ops: Optional[CampaignGraphOps] = None


def get_graph_ops() -> CampaignGraphOps:
    """Get or create graph operations instance."""
    global _graph_ops
    if _graph_ops is None:
        _graph_ops = CampaignGraphOps()
    return _graph_ops


class EntityBase(BaseModel):
    """Base entity model."""

    name: str
    entity_type: str
    description: Optional[str] = None
    properties: dict = {}


class EntityCreate(EntityBase):
    """Entity creation model."""

    pass


class EntityResponse(EntityBase):
    """Entity response model."""

    id: str
    aliases: list[str] = []
    created_at: Optional[str] = None


class RelationshipCreate(BaseModel):
    """Relationship creation model."""

    source_id: str
    target_id: str
    relationship_type: str
    properties: dict = {}


@router.get("/entities")
async def list_entities(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List campaign entities."""
    try:
        ops = get_graph_ops()
        entities = ops.list_entities(entity_type=entity_type, limit=limit)
        return {"entities": entities, "total": len(entities)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str) -> EntityResponse:
    """Get a specific entity by ID."""
    try:
        ops = get_graph_ops()
        entity = ops.get_entity(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        return EntityResponse(**entity)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/entities", response_model=EntityResponse)
async def create_entity(entity: EntityCreate) -> EntityResponse:
    """Create a new campaign entity."""
    try:
        ops = get_graph_ops()
        created = ops.create_entity(
            name=entity.name,
            entity_type=entity.entity_type,
            description=entity.description,
            properties=entity.properties,
        )
        return EntityResponse(**created)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/{entity_id}/neighbors")
async def get_entity_neighbors(
    entity_id: str,
    max_hops: int = Query(1, ge=1, le=3),
    relationship_types: Optional[str] = Query(None, description="Comma-separated relationship types"),
) -> dict:
    """Get neighboring entities within N hops."""
    try:
        ops = get_graph_ops()
        rel_types = relationship_types.split(",") if relationship_types else None
        neighbors = ops.get_neighbors(
            entity_id=entity_id,
            max_hops=max_hops,
            relationship_types=rel_types,
        )
        return {"entity_id": entity_id, "neighbors": neighbors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/relationships")
async def create_relationship(rel: RelationshipCreate) -> dict:
    """Create a relationship between entities."""
    try:
        ops = get_graph_ops()
        result = ops.create_relationship(
            source_id=rel.source_id,
            target_id=rel.target_id,
            relationship_type=rel.relationship_type,
            properties=rel.properties,
        )
        return {"success": True, "relationship": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_graph(
    q: str = Query(..., description="Search query"),
    entity_types: Optional[str] = Query(None, description="Comma-separated entity types"),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """Search the campaign knowledge graph."""
    try:
        ops = get_graph_ops()
        types = entity_types.split(",") if entity_types else None
        results = ops.search(query=q, entity_types=types, limit=limit)
        return {"query": q, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
