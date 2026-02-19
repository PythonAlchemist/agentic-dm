"""Audio transcription endpoints with speaker diarization."""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks, Form
from pydantic import BaseModel

from backend.audio.models import (
    AudioJob,
    AudioJobPhase,
    DiarizedTranscript,
    SpeakerMappingEntry,
    SpeakerMappingRequest,
)
from backend.audio.transcriber import DeepgramTranscriber
from backend.audio.converter import DiarizedTranscriptConverter
from backend.core.config import settings
from backend.ner import NERConfig
from backend.transcript import TranscriptProcessor

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = (".mp3", ".wav", ".m4a", ".webm", ".ogg", ".flac")

# In-memory job tracking
_audio_jobs: dict[str, AudioJob] = {}


async def _transcribe_background(job_id: str, filepath: str):
    """Background task: transcribe audio via Deepgram."""
    job = _audio_jobs[job_id]
    try:
        job.phase = AudioJobPhase.TRANSCRIBING

        transcriber = DeepgramTranscriber()
        result = await transcriber.transcribe_file(filepath)

        job.diarized_transcript = result
        job.phase = AudioJobPhase.AWAITING_MAPPING

        logger.info(
            "Transcription complete for job %s: %d speakers, %d segments",
            job_id,
            result.speaker_count,
            len(result.segments),
        )

    except Exception as e:
        logger.error("Transcription failed for job %s: %s", job_id, e)
        job.phase = AudioJobPhase.FAILED
        job.error = str(e)


async def _process_transcript_background(
    job_id: str,
    content: str,
    speakers: list[dict],
    session_number: Optional[int],
    campaign_id: Optional[str],
):
    """Background task: feed converted transcript into TranscriptProcessor."""
    job = _audio_jobs[job_id]
    try:
        job.phase = AudioJobPhase.PROCESSING_TRANSCRIPT

        config = NERConfig(
            use_llm_extraction=True,
            link_to_graph=True,
            create_missing_entities=True,
        )
        processor = TranscriptProcessor(
            ner_config=config,
            create_entities=True,
        )

        result = await processor.process(
            content=content,
            session_number=session_number,
            campaign_id=campaign_id,
            speakers=speakers,
            format_hint="timestamped",
        )

        job.transcript_result = {
            "session_id": result.session_id,
            "session_number": result.session_number,
            "campaign_id": result.campaign_id,
            "segments_processed": result.segments_processed,
            "entities_extracted": result.entities_extracted,
            "entities_created": result.entities_created,
            "relationships_extracted": result.relationships_extracted,
            "relationships_created": result.relationships_created,
            "entity_counts": result.entity_counts,
            "processing_time_ms": result.processing_time_ms,
            "errors": result.errors,
        }
        job.phase = AudioJobPhase.COMPLETED

        logger.info(
            "Transcript processing complete for job %s: %d entities",
            job_id,
            result.entities_extracted,
        )

    except Exception as e:
        logger.error("Transcript processing failed for job %s: %s", job_id, e)
        job.phase = AudioJobPhase.FAILED
        job.error = str(e)


@router.post("/upload")
async def upload_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_number: Optional[int] = Form(None),
):
    """Upload an audio file for transcription with speaker diarization.

    Accepts mp3, wav, m4a, webm, ogg, flac.
    Returns a job_id to poll for status.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    if not settings.deepgram_api_key:
        raise HTTPException(
            status_code=500,
            detail="Deepgram API key not configured. Set DEEPGRAM_API_KEY in .env",
        )

    job_id = str(uuid.uuid4())

    # Save audio file
    audio_dir = settings.audio_dir
    audio_dir.mkdir(parents=True, exist_ok=True)
    filepath = audio_dir / f"{job_id}{ext}"

    try:
        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Create job
    job = AudioJob(
        job_id=job_id,
        filename=file.filename,
        phase=AudioJobPhase.UPLOADING,
    )
    _audio_jobs[job_id] = job

    # Start background transcription
    background_tasks.add_task(_transcribe_background, job_id, str(filepath))

    return {
        "job_id": job_id,
        "filename": file.filename,
        "message": "Audio upload started, transcription in progress",
    }


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    """Poll job status.

    When awaiting_mapping: includes speaker_samples.
    When completed: includes transcript_result.
    """
    job = _audio_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response: dict = {
        "job_id": job.job_id,
        "filename": job.filename,
        "phase": job.phase.value,
    }

    if job.error:
        response["error"] = job.error

    if job.phase == AudioJobPhase.AWAITING_MAPPING and job.diarized_transcript:
        response["speaker_samples"] = [
            s.model_dump() for s in job.diarized_transcript.speaker_samples
        ]
        response["total_duration"] = job.diarized_transcript.total_duration
        response["segment_count"] = len(job.diarized_transcript.segments)

    if job.phase == AudioJobPhase.COMPLETED and job.transcript_result:
        response["transcript_result"] = job.transcript_result

    return response


@router.post("/{job_id}/map-speakers")
async def map_speakers(
    job_id: str,
    request: SpeakerMappingRequest,
    background_tasks: BackgroundTasks,
):
    """Map detected speakers to players/characters and process the transcript.

    The job must be in awaiting_mapping phase.
    """
    job = _audio_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.phase != AudioJobPhase.AWAITING_MAPPING:
        raise HTTPException(
            status_code=400,
            detail=f"Job is in '{job.phase.value}' phase, expected 'awaiting_mapping'",
        )

    if not job.diarized_transcript:
        raise HTTPException(status_code=500, detail="No transcription data available")

    # Convert diarized transcript to text format
    converter = DiarizedTranscriptConverter(
        transcript=job.diarized_transcript,
        mappings=request.mappings,
    )
    transcript_text = converter.to_transcript_text()
    speaker_defs = converter.to_speaker_defs()

    # Start background transcript processing
    background_tasks.add_task(
        _process_transcript_background,
        job_id,
        transcript_text,
        speaker_defs,
        request.session_number,
        request.campaign_id,
    )

    return {
        "job_id": job_id,
        "message": "Speaker mappings applied, processing transcript",
        "phase": AudioJobPhase.PROCESSING_TRANSCRIPT.value,
    }


@router.get("/jobs")
async def list_jobs():
    """List all audio transcription jobs."""
    jobs = []
    for job in _audio_jobs.values():
        entry: dict = {
            "job_id": job.job_id,
            "filename": job.filename,
            "phase": job.phase.value,
        }
        if job.error:
            entry["error"] = job.error
        jobs.append(entry)
    return {"jobs": jobs}
