"""Transcript processing endpoints."""

import os
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.ner import NERConfig
from backend.transcript import TranscriptProcessor


router = APIRouter()


class SpeakerDefinition(BaseModel):
    """Definition of a known speaker."""

    name: str
    role: str = "unknown"  # dm, player, unknown
    character_name: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class TranscriptRequest(BaseModel):
    """Request body for transcript processing."""

    content: str
    session_number: Optional[int] = None
    campaign_id: Optional[str] = None
    speakers: Optional[list[SpeakerDefinition]] = None
    format_hint: Optional[str] = None  # json, discord, plain, timestamped
    use_llm: bool = True
    create_entities: bool = True


class TranscriptResponse(BaseModel):
    """Response from transcript processing."""

    session_id: str
    session_number: Optional[int] = None
    campaign_id: Optional[str] = None
    segments_processed: int
    entities_extracted: int
    entities_created: int
    relationships_extracted: int
    relationships_created: int
    entity_counts: dict[str, int]
    processing_time_ms: float
    errors: list[str] = Field(default_factory=list)


class TranscriptJobStatus(BaseModel):
    """Status of a transcript processing job."""

    job_id: str
    status: str  # pending, processing, completed, failed
    filename: Optional[str] = None
    result: Optional[TranscriptResponse] = None
    error: Optional[str] = None


# In-memory job tracking
_transcript_jobs: dict[str, TranscriptJobStatus] = {}


async def process_transcript_background(
    job_id: str,
    content: str,
    session_number: Optional[int],
    campaign_id: Optional[str],
    speakers: Optional[list[dict]],
    format_hint: Optional[str],
    use_llm: bool,
    create_entities: bool,
):
    """Background task to process transcript."""
    try:
        _transcript_jobs[job_id].status = "processing"

        # Configure NER
        config = NERConfig(
            use_llm_extraction=use_llm,
            link_to_graph=True,
            create_missing_entities=create_entities,
        )

        processor = TranscriptProcessor(
            ner_config=config,
            create_entities=create_entities,
        )

        result = await processor.process(
            content=content,
            session_number=session_number,
            campaign_id=campaign_id,
            speakers=speakers,
            format_hint=format_hint,
        )

        _transcript_jobs[job_id].status = "completed"
        _transcript_jobs[job_id].result = TranscriptResponse(
            session_id=result.session_id,
            session_number=result.session_number,
            campaign_id=result.campaign_id,
            segments_processed=result.segments_processed,
            entities_extracted=result.entities_extracted,
            entities_created=result.entities_created,
            relationships_extracted=result.relationships_extracted,
            relationships_created=result.relationships_created,
            entity_counts=result.entity_counts,
            processing_time_ms=result.processing_time_ms,
            errors=result.errors,
        )

    except Exception as e:
        _transcript_jobs[job_id].status = "failed"
        _transcript_jobs[job_id].error = str(e)


@router.post("/process", response_model=TranscriptResponse)
async def process_transcript(request: TranscriptRequest) -> TranscriptResponse:
    """Process a transcript synchronously.

    Use this for smaller transcripts. For larger transcripts,
    use /process/async endpoint.
    """
    try:
        # Configure NER
        config = NERConfig(
            use_llm_extraction=request.use_llm,
            link_to_graph=True,
            create_missing_entities=request.create_entities,
        )

        processor = TranscriptProcessor(
            ner_config=config,
            create_entities=request.create_entities,
        )

        # Convert speakers
        speakers = None
        if request.speakers:
            speakers = [s.model_dump() for s in request.speakers]

        result = await processor.process(
            content=request.content,
            session_number=request.session_number,
            campaign_id=request.campaign_id,
            speakers=speakers,
            format_hint=request.format_hint,
        )

        return TranscriptResponse(
            session_id=result.session_id,
            session_number=result.session_number,
            campaign_id=result.campaign_id,
            segments_processed=result.segments_processed,
            entities_extracted=result.entities_extracted,
            entities_created=result.entities_created,
            relationships_extracted=result.relationships_extracted,
            relationships_created=result.relationships_created,
            entity_counts=result.entity_counts,
            processing_time_ms=result.processing_time_ms,
            errors=result.errors,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/async")
async def process_transcript_async(
    background_tasks: BackgroundTasks,
    request: TranscriptRequest,
) -> dict:
    """Process a transcript asynchronously.

    Returns a job_id to check status with /status/{job_id}.
    """
    job_id = str(uuid.uuid4())

    # Convert speakers
    speakers = None
    if request.speakers:
        speakers = [s.model_dump() for s in request.speakers]

    # Create job status
    _transcript_jobs[job_id] = TranscriptJobStatus(
        job_id=job_id,
        status="pending",
    )

    # Start background processing
    background_tasks.add_task(
        process_transcript_background,
        job_id,
        request.content,
        request.session_number,
        request.campaign_id,
        speakers,
        request.format_hint,
        request.use_llm,
        request.create_entities,
    )

    return {"job_id": job_id, "message": "Transcript processing started"}


@router.post("/upload")
async def upload_transcript(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_number: Optional[int] = None,
    campaign_id: Optional[str] = None,
    use_llm: bool = True,
    create_entities: bool = True,
) -> dict:
    """Upload and process a transcript file.

    Supports .txt and .json files.
    """
    # Validate file type
    valid_extensions = (".txt", ".json", ".md")
    if not any(file.filename.lower().endswith(ext) for ext in valid_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"Only {', '.join(valid_extensions)} files are supported",
        )

    job_id = str(uuid.uuid4())

    try:
        # Read file content
        content = await file.read()
        content_str = content.decode("utf-8")

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")

    # Detect format hint from extension
    format_hint = None
    if file.filename.lower().endswith(".json"):
        format_hint = "json"

    # Create job status
    _transcript_jobs[job_id] = TranscriptJobStatus(
        job_id=job_id,
        status="pending",
        filename=file.filename,
    )

    # Start background processing
    background_tasks.add_task(
        process_transcript_background,
        job_id,
        content_str,
        session_number,
        campaign_id,
        None,  # speakers
        format_hint,
        use_llm,
        create_entities,
    )

    return {
        "job_id": job_id,
        "message": "Transcript upload started",
        "filename": file.filename,
    }


@router.get("/status/{job_id}", response_model=TranscriptJobStatus)
async def get_job_status(job_id: str) -> TranscriptJobStatus:
    """Get the status of a transcript processing job."""
    if job_id not in _transcript_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _transcript_jobs[job_id]


@router.get("/jobs")
async def list_jobs() -> dict:
    """List all transcript processing jobs."""
    return {"jobs": list(_transcript_jobs.values())}
