"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.api.auth import (
    OPEN_PATHS,
    MisconfiguredTokens,
    identify,
    readers,
)
from backend.api.routes import (
    audio,
    campaign,
    chat,
    combat,
    homebrew,
    lab,
    npc_discord,
    players,
    shop,
    transcript,
)
from backend.core.config import settings


class ReaderGate:
    """Refuse anything under `/api` without a reader token.

    RAW ASGI RATHER THAN A ROUTE DEPENDENCY because the chat router carries a
    WebSocket, and a dependency that raises `HTTPException` has no response to
    raise it into. At this level both scopes look the same and the guarantee is
    the simple one: nothing under `/api` answers without a token, whatever kind
    of route it turns out to be.

    THE WEBSOCKET IS GATED BY THE SAME RULE and accepts a valid token like any
    other route -- but a browser cannot set a header on a WebSocket handshake,
    so it is unreachable from `web/` while the deployment is gated. Nothing in
    `web/` opens it, so that costs nothing today. If it is ever wired up it
    needs a real handshake; the token in a query string is not the answer,
    since that puts a credential in every proxy log and referrer.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not readers():
            await self.app(scope, receive, send)
            return
        if scope.get("path", "") in OPEN_PATHS:
            await self.app(scope, receive, send)
            return

        # PREFLIGHT IS NOT A READ. The browser sends `OPTIONS` without the
        # `Authorization` header by design, so gating it would fail every
        # cross-origin call before the real request was ever made. It carries
        # no book text; CORS below decides whether it is answered.
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        offered = ""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                scheme, _, token = value.decode("latin-1").partition(" ")
                if scheme.lower() == "bearer":
                    offered = token.strip()
                break

        who = identify(offered)
        if who:
            # THE NAME TRAVELS. `identify` returns WHO, and this used to throw
            # that away -- so the per-person-token design's whole payoff, that
            # "a leaked token says whose it was", never reached a request. No
            # log carried a name and no route could know its caller. Stashed on
            # the scope, which both HTTP and WebSocket handlers can read, and
            # `require_reader` returns it to any route that asks.
            scope["reader"] = who
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse(
            {"detail": "this deployment is private; a reader token is required"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup: ensure data directories exist
    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    settings.transcript_dir.mkdir(parents=True, exist_ok=True)
    settings.audio_dir.mkdir(parents=True, exist_ok=True)

    # SAID OUT LOUD, BOTH WAYS. The graph holds the prose of two published
    # books, so "did the tokens get set" is the one deployment question worth
    # answering at startup rather than by trying the URL in a private window.
    # A MALFORMED VALUE STOPS THE PROCESS rather than opening the gate. Unset
    # is a deliberate, documented open; set-but-unparseable is a mistake, and
    # the mistake used to serve two books to anyone who found the URL while the
    # frontend's stored token went on working, so nobody would notice.
    try:
        known = readers()
    except MisconfiguredTokens as exc:
        print(f"[auth] REFUSING TO START -- {exc}")
        raise
    if known:
        print(f"[auth] gated -- {len(known)} reader(s): {', '.join(sorted(known.values()))}")
    else:
        print("[auth] OPEN -- no ACCESS_TOKENS set; every endpoint answers anyone")

    yield

    # Shutdown: cleanup if needed
    pass


app = FastAPI(
    title="D&D DM Assistant",
    description="AI-powered Dungeon Master Assistant with RAG and Knowledge Graph",
    version="0.1.0",
    lifespan=lifespan,
)

# ORDER MATTERS, AND IT IS THE REVERSE OF WHAT IT READS AS. Starlette builds
# the stack so that the LAST middleware added is the OUTERMOST, so adding the
# gate first and CORS second puts CORS around it -- which is what makes a 401
# arrive at the browser as a 401 rather than as an opaque CORS failure the
# frontend cannot tell apart from the API being down.
app.add_middleware(ReaderGate)

_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    # THE CREDENTIAL IS A BEARER TOKEN, NOT A COOKIE, so the browser never
    # needs to attach one on our behalf -- and `allow_credentials` alongside
    # `allow_origins=["*"]` is a combination the CORS spec forbids outright.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(campaign.router, prefix="/api/campaign", tags=["Campaign"])
app.include_router(transcript.router, prefix="/api/transcript", tags=["Transcript"])
app.include_router(players.router, prefix="/api", tags=["Players"])
app.include_router(npc_discord.router, prefix="/api", tags=["NPC Discord"])
app.include_router(combat.router, prefix="/api", tags=["Combat"])
app.include_router(shop.router, prefix="/api", tags=["Shop"])
app.include_router(audio.router, prefix="/api/audio", tags=["Audio"])
app.include_router(lab.router, prefix="/api/lab", tags=["Agent Lab"])
app.include_router(homebrew.router, prefix="/api/homebrew", tags=["Homebrew"])


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
