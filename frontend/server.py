#!/usr/bin/env python3
"""
FastAPI server for the Agentic DM frontend.
"""

import sys
import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import uvicorn
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading
import time

# Add parent directory to path for backend imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI(
    title="Agentic DM API",
    description="AI-powered Dungeon Master assistant API",
    version="1.0.0",
)

# Mount static files from current directory
app.mount("/static", StaticFiles(directory="."), name="static")

# Initialize the RAG system
rag_system = None

# Debug mode - set to True to see OpenAI responses in terminal
DEBUG_MODE = True


# Hot reload setup
class HotReloadHandler(FileSystemEventHandler):
    def __init__(self, app):
        self.app = app
        self.last_reload = time.time()

    def on_modified(self, event):
        if event.is_directory:
            return

        # Only reload for frontend files
        if event.src_path.endswith((".html", ".css", ".js")):
            current_time = time.time()
            # Debounce reloads to avoid multiple rapid reloads
            if current_time - self.last_reload > 1:
                self.last_reload = current_time
                print(f"🔄 Frontend file changed: {event.src_path}")
                print("💡 Refresh your browser to see changes!")


def start_hot_reload():
    """Start the file watcher for hot reload."""
    event_handler = HotReloadHandler(app)
    observer = Observer()
    observer.schedule(event_handler, path=".", recursive=False)
    observer.start()
    print("🔥 Hot reload enabled - watching for frontend file changes")
    return observer


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str
    question_type: str


@app.on_event("startup")
async def startup_event():
    """Initialize the RAG system on startup."""
    global rag_system
    try:
        print("🔧 Initializing OpenAI RAG system...")
        # Import here to avoid circular import issues
        from backend.openai_rag import OpenAIRAGSystem

        rag_system = OpenAIRAGSystem()

        # Try to load existing index
        index_name = "armyofthedamned"
        index_path = f"../indices/{index_name}"

        embeddings_file = f"{index_path}_embeddings.npy"
        metadata_file = f"{index_path}_metadata.json"

        if os.path.exists(embeddings_file) and os.path.exists(metadata_file):
            print(f"📚 Loading existing index from {index_path}...")
            try:
                rag_system.load_index(index_path)
                chunk_count = len(rag_system.chunks)
                print(f"✅ Index loaded successfully with {chunk_count} chunks")
            except Exception as e:
                print(f"❌ Failed to load existing index: {e}")
                print("🔄 Will create new index when needed...")
        else:
            print("📖 No existing index found. Will create new one when needed...")

    except Exception as e:
        print(f"❌ Failed to initialize RAG system: {e}")
        print("💡 Make sure your .env file has OPENAI_API_KEY set")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page with hot reload script."""
    try:
        with open("index.html", "r") as f:
            html_content = f.read()

        # Add hot reload script for development
        hot_reload_script = """
        <script>
        // Hot reload for development
        if (window.location.hostname === 'localhost' || 
            window.location.hostname === '127.0.0.1') {
            const ws = new WebSocket('ws://localhost:8000/ws');
            ws.onmessage = function(event) {
                if (event.data === 'reload') {
                    console.log('🔄 Hot reload triggered');
                    window.location.reload();
                }
            };
            ws.onerror = function() {
                // WebSocket not available, fall back to polling
                setInterval(() => {
                    fetch('/api/check-reload')
                        .then(response => response.json())
                        .then(data => {
                            if (data.reload) {
                                console.log('🔄 Hot reload triggered');
                                window.location.reload();
                            }
                        })
                        .catch(() => {});
                }, 1000);
            };
        }
        </script>
        """

        # Insert the script before the closing body tag
        html_content = html_content.replace("</body>", f"{hot_reload_script}</body>")
        return HTMLResponse(content=html_content)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/styles.css")
async def styles():
    """Serve CSS file."""
    return FileResponse("styles.css", media_type="text/css")


@app.get("/script.js")
async def script():
    """Serve JavaScript file."""
    return FileResponse("script.js", media_type="application/javascript")


@app.get("/api/check-reload")
async def check_reload():
    """Check if frontend files have changed."""
    # Simple implementation - in production you'd want more sophisticated detection
    return {"reload": False}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat API endpoint using real RAG system."""
    try:
        message = request.message.strip()

        if not message:
            raise HTTPException(status_code=400, detail="Message is required")

        if rag_system is None:
            raise HTTPException(status_code=500, detail="RAG system not initialized")

        if DEBUG_MODE:
            print(f"\n🔍 DEBUG: User Question: {message}")

        # Get relevant context from the RAG system
        context = rag_system.get_context_for_query(
            message, top_k=15, include_surrounding=True, max_context_length=10000
        )

        if DEBUG_MODE:
            print(f"📖 DEBUG: Retrieved Context Length: {len(context)} characters")
            print(f"📖 DEBUG: Context Preview: {context[:200]}...")

            # Show which sections are being retrieved
            if "[" in context:
                sections = [
                    line for line in context.split("\n") if line.strip().startswith("[")
                ]
                print(f"📚 DEBUG: Content sections found:")
                for section in sections[:5]:  # Show first 5 sections
                    print(f"   - {section}")
                if len(sections) > 5:
                    print(f"   ... and {len(sections) - 5} more sections")

        if context == "No relevant information found for your query.":
            raise HTTPException(
                status_code=404, detail="No relevant information found. Try rephrasing."
            )

        # Use OpenAI to generate a response
        answer = rag_system.ask_question(message, context)

        if DEBUG_MODE:
            print(f"🤖 DEBUG: OpenAI Response:")
            print("=" * 80)
            print(answer)
            print("=" * 80)

        # Detect question type for response formatting
        question_type = rag_system._detect_question_type(message)

        if DEBUG_MODE:
            print(f"🏷️  DEBUG: Detected Question Type: {question_type}")

        return ChatResponse(answer=answer, question_type=question_type)

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Chat API error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {str(e)}"
        )


@app.get("/api/status")
async def status():
    """Get system status from RAG system."""
    try:
        if rag_system is None:
            return {"status": "disconnected", "error": "RAG system not initialized"}

        stats = rag_system.get_statistics()
        return {
            "status": "connected",
            "model": "GPT-3.5-turbo",
            "chunks_indexed": stats.get("total_chunks", 0),
            "content_types": list(stats.get("content_types", {}).keys()),
            "embedding_dimensions": stats.get("embedding_dimensions", 0),
            "total_text_length": stats.get("total_text_length", 0),
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/index-pdf")
async def index_pdf():
    """Index a PDF file."""
    try:
        if rag_system is None:
            raise HTTPException(status_code=500, detail="RAG system not initialized")

        # Default to armyofthedamned.pdf
        pdf_path = "../data/armyofthedamned.pdf"

        if not os.path.exists(pdf_path):
            raise HTTPException(
                status_code=404, detail=f"PDF file not found: {pdf_path}"
            )

        print(f"📖 Indexing PDF: {pdf_path}")
        rag_system.parse_and_index_pdf(
            pdf_path, percentage=100, save_index=True, index_name="armyofthedamned"
        )

        return {"message": "PDF indexed successfully", "chunks": len(rag_system.chunks)}

    except Exception as e:
        print(f"❌ Indexing error: {e}")
        raise HTTPException(status_code=500, detail=f"Error indexing PDF: {str(e)}")


if __name__ == "__main__":
    print("🚀 Starting Agentic DM FastAPI Server...")
    print("📱 Frontend will be available at: http://localhost:8000")
    print("🔌 API endpoints:")
    print("   - GET  /          → Frontend page")
    print("   - POST /api/chat  → Chat endpoint")
    print("   - GET  /api/status → System status")
    print("   - POST /api/index-pdf → Index PDF")
    print("📚 API docs: http://localhost:8000/docs")
    print("🔥 Hot reload enabled for frontend development")
    if DEBUG_MODE:
        print("🐛 DEBUG MODE: OpenAI responses will be logged to terminal")
    print()

    # Start hot reload in a separate thread
    hot_reload_thread = threading.Thread(target=start_hot_reload, daemon=True)
    hot_reload_thread.start()

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
