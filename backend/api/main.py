"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import chat, search, campaign, ingest, transcript, players, npc_discord, combat, shop
from backend.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup: ensure data directories exist
    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    settings.transcript_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)

    yield

    # Shutdown: cleanup if needed
    pass


app = FastAPI(
    title="D&D DM Assistant",
    description="AI-powered Dungeon Master Assistant with RAG and Knowledge Graph",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(search.router, prefix="/api/search", tags=["Search"])
app.include_router(campaign.router, prefix="/api/campaign", tags=["Campaign"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["Ingestion"])
app.include_router(transcript.router, prefix="/api/transcript", tags=["Transcript"])
app.include_router(players.router, prefix="/api", tags=["Players"])
app.include_router(npc_discord.router, prefix="/api", tags=["NPC Discord"])
app.include_router(combat.router, prefix="/api", tags=["Combat"])
app.include_router(shop.router, prefix="/api", tags=["Shop"])


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "D&D DM Assistant",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "components": {
            "api": "ok",
            "openai": "configured" if settings.openai_api_key else "missing",
        },
    }
