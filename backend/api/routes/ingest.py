"""Document ingestion endpoints."""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel

from backend.core.config import settings
from backend.ingestion.pdf_processor import PDFProcessor
from backend.ingestion.embeddings import EmbeddingPipeline

router = APIRouter()


class IngestionStatus(BaseModel):
    """Status of an ingestion job."""

    job_id: str
    status: str  # "pending", "processing", "completed", "failed"
    filename: str
    chunks_processed: int = 0
    total_chunks: int = 0
    error: Optional[str] = None


class IngestionResponse(BaseModel):
    """Response after starting ingestion."""

    job_id: str
    message: str
    filename: str


# Simple in-memory job tracking (replace with Redis/DB for production)
_ingestion_jobs: dict[str, IngestionStatus] = {}


async def process_pdf_background(job_id: str, filepath: str, filename: str):
    """Background task to process PDF."""
    try:
        _ingestion_jobs[job_id].status = "processing"

        # Process PDF
        processor = PDFProcessor()
        chunks = processor.process(filepath)

        _ingestion_jobs[job_id].total_chunks = len(chunks)

        # Generate embeddings and store
        pipeline = EmbeddingPipeline()
        for i, chunk in enumerate(chunks):
            await pipeline.embed_and_store(chunk)
            _ingestion_jobs[job_id].chunks_processed = i + 1

        _ingestion_jobs[job_id].status = "completed"

    except Exception as e:
        _ingestion_jobs[job_id].status = "failed"
        _ingestion_jobs[job_id].error = str(e)

    finally:
        # Cleanup uploaded file
        if os.path.exists(filepath):
            os.remove(filepath)


@router.post("/pdf", response_model=IngestionResponse)
async def ingest_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> IngestionResponse:
    """Upload and ingest a PDF document."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Generate job ID
    import uuid
    job_id = str(uuid.uuid4())

    # Save uploaded file
    filepath = settings.pdf_dir / f"{job_id}_{file.filename}"
    try:
        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Create job status
    _ingestion_jobs[job_id] = IngestionStatus(
        job_id=job_id,
        status="pending",
        filename=file.filename,
    )

    # Start background processing
    background_tasks.add_task(
        process_pdf_background,
        job_id,
        str(filepath),
        file.filename,
    )

    return IngestionResponse(
        job_id=job_id,
        message="PDF ingestion started",
        filename=file.filename,
    )


@router.get("/status/{job_id}", response_model=IngestionStatus)
async def get_ingestion_status(job_id: str) -> IngestionStatus:
    """Get the status of an ingestion job."""
    if job_id not in _ingestion_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _ingestion_jobs[job_id]


@router.get("/jobs")
async def list_jobs() -> dict:
    """List all ingestion jobs."""
    return {"jobs": list(_ingestion_jobs.values())}


@router.post("/pdf/sync")
async def ingest_pdf_sync(file: UploadFile = File(...)) -> dict:
    """Synchronously ingest a PDF (for smaller files)."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    try:
        # Save file temporarily
        import uuid
        temp_path = settings.pdf_dir / f"temp_{uuid.uuid4()}_{file.filename}"
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        # Process
        processor = PDFProcessor()
        chunks = processor.process(str(temp_path))

        # Embed and store
        pipeline = EmbeddingPipeline()
        for chunk in chunks:
            await pipeline.embed_and_store(chunk)

        # Cleanup
        os.remove(temp_path)

        return {
            "success": True,
            "filename": file.filename,
            "chunks_processed": len(chunks),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
