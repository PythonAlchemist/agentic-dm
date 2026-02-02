"""Search endpoints for RAG retrieval."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.rag.retriever import HybridRetriever

router = APIRouter()

_retriever: Optional[HybridRetriever] = None


def get_retriever() -> HybridRetriever:
    """Get or create retriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever


class SearchResult(BaseModel):
    """A single search result."""

    content: str
    source: str
    page: Optional[int] = None
    chunk_id: str
    score: float
    metadata: dict = {}


class SearchResponse(BaseModel):
    """Search response with results."""

    query: str
    results: list[SearchResult]
    total: int


@router.get("/", response_model=SearchResponse)
async def search(
    q: str = Query(..., description="Search query"),
    k: int = Query(5, ge=1, le=20, description="Number of results"),
    source_filter: Optional[str] = Query(None, description="Filter by source"),
) -> SearchResponse:
    """Search the document collection."""
    try:
        retriever = get_retriever()
        results = await retriever.search(
            query=q,
            top_k=k,
            source_filter=source_filter,
        )

        return SearchResponse(
            query=q,
            results=[
                SearchResult(
                    content=r["content"],
                    source=r["metadata"].get("source", "unknown"),
                    page=r["metadata"].get("page"),
                    chunk_id=r["id"],
                    score=r["score"],
                    metadata=r["metadata"],
                )
                for r in results
            ],
            total=len(results),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources")
async def list_sources() -> dict:
    """List all available document sources."""
    try:
        retriever = get_retriever()
        sources = await retriever.list_sources()
        return {"sources": sources}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
