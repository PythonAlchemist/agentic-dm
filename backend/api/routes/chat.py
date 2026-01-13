"""Chat endpoint for DM Assistant interactions."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.rag.pipeline import RAGPipeline

router = APIRouter()

# Initialize RAG pipeline (lazy loading)
_rag_pipeline: Optional[RAGPipeline] = None


def get_rag_pipeline() -> RAGPipeline:
    """Get or create RAG pipeline instance."""
    global _rag_pipeline
    if _rag_pipeline is None:
        _rag_pipeline = RAGPipeline()
    return _rag_pipeline


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Chat request payload."""

    message: str
    conversation_history: list[ChatMessage] = []
    mode: str = "assistant"  # "assistant" or "autonomous"
    campaign_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response payload."""

    response: str
    sources: list[dict] = []
    mode: str


class SourceInfo(BaseModel):
    """Information about a retrieved source."""

    source: str
    page: Optional[int] = None
    chunk_id: str
    relevance_score: float


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a chat message and return DM response."""
    try:
        pipeline = get_rag_pipeline()

        # Build context from conversation history
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in request.conversation_history
        ]

        # Get response from RAG pipeline
        result = await pipeline.query(
            question=request.message,
            conversation_history=history,
            mode=request.mode,
        )

        return ChatResponse(
            response=result["response"],
            sources=result.get("sources", []),
            mode=request.mode,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simple")
async def simple_chat(message: str) -> dict:
    """Simple chat endpoint for quick testing."""
    try:
        pipeline = get_rag_pipeline()
        result = await pipeline.query(question=message)
        return {"response": result["response"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
