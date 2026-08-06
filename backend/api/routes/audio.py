"""Audio transcription endpoints with speaker diarization."""

import json
import logging
import uuid
from datetime import datetime
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
from backend.ner.models import ExtractedEntity, ExtractedRelationship
from backend.transcript import TranscriptProcessor

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = (".mp3", ".wav", ".m4a", ".webm", ".ogg", ".flac")

# In-memory job tracking
_audio_jobs: dict[str, AudioJob] = {}


def _save_transcript_history(
    job: AudioJob,
    transcript_text: str,
    speakers: list[dict],
    session_number: Optional[int],
    campaign_id: Optional[str],
) -> None:
    """Persist completed transcript as a JSON file for history browsing."""
    transcript_dir = settings.transcript_dir
    transcript_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "job_id": job.job_id,
        "filename": job.filename,
        "completed_at": datetime.utcnow().isoformat(),
        "session_number": session_number,
        "campaign_id": campaign_id,
        "speaker_mappings": speakers,
        "transcript_text": transcript_text,
        "transcript_result": job.transcript_result,
        "total_duration": (
            job.diarized_transcript.total_duration
            if job.diarized_transcript
            else None
        ),
        "segment_count": (
            len(job.diarized_transcript.segments)
            if job.diarized_transcript
            else None
        ),
    }

    filepath = transcript_dir / f"{job.job_id}.json"
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Saved transcript history for job %s to %s", job.job_id, filepath)


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
    """Background task: extract entities without writing to graph, then await review."""
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
            create_entities=False,
            create_relationships=False,
        )

        result = await processor.process(
            content=content,
            session_number=session_number,
            campaign_id=campaign_id,
            speakers=speakers,
            format_hint="timestamped",
        )

        # Store extraction results for review
        job.pending_entities = [
            {
                "name": e.normalized_name or e.text,
                "entity_type": e.entity_type.value,
                "confidence": e.confidence,
            }
            for e in result.all_entities
        ]
        job.pending_relationships = [
            {
                "source": r.source_entity_name,
                "target": r.target_entity_name,
                "type": r.relationship_type.value,
            }
            for r in result.all_relationships
        ]
        # Store full serialized models for graph commit on confirm
        job.pending_raw_entities = [e.model_dump(mode="json") for e in result.all_entities]
        job.pending_raw_relationships = [r.model_dump(mode="json") for r in result.all_relationships]
        job.pending_transcript_text = content
        job.pending_speaker_defs = speakers
        job.pending_session_number = session_number
        job.pending_campaign_id = campaign_id
        job.pending_session_id = result.session_id
        job.pending_entity_counts = result.entity_counts
        job.pending_processing_time_ms = result.processing_time_ms
        job.pending_segments_processed = result.segments_processed
        job.pending_errors = result.errors

        job.phase = AudioJobPhase.AWAITING_REVIEW

        logger.info(
            "Entity extraction complete for job %s: %d entities, %d relationships awaiting review",
            job_id,
            result.entities_extracted,
            result.relationships_extracted,
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

        # Merge adjacent same-speaker segments for cleaner transcript display
        merged = []
        for seg in job.diarized_transcript.segments:
            if merged and merged[-1]["speaker"] == seg.speaker:
                prev = merged[-1]
                prev["text"] += " " + seg.text
                prev["end"] = seg.end
                prev["confidence"] = min(prev["confidence"], seg.confidence)
            else:
                merged.append({
                    "speaker": seg.speaker,
                    "text": seg.text,
                    "start": seg.start,
                    "end": seg.end,
                    "confidence": seg.confidence,
                })
        response["segments"] = merged

    if job.phase == AudioJobPhase.AWAITING_REVIEW:
        response["entities"] = job.pending_entities or []
        response["relationships"] = job.pending_relationships or []
        response["entity_counts"] = job.pending_entity_counts or {}
        response["segments_processed"] = job.pending_segments_processed or 0

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


@router.post("/{job_id}/confirm")
async def confirm_entities(job_id: str):
    """Confirm extracted entities and write them to the knowledge graph.

    The job must be in awaiting_review phase.
    """
    job = _audio_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.phase != AudioJobPhase.AWAITING_REVIEW:
        raise HTTPException(
            status_code=400,
            detail=f"Job is in '{job.phase.value}' phase, expected 'awaiting_review'",
        )

    if not job.pending_raw_entities:
        raise HTTPException(status_code=400, detail="No pending entities to confirm")

    try:
        # Reconstruct extracted objects
        entities = [ExtractedEntity(**e) for e in job.pending_raw_entities]
        relationships = [ExtractedRelationship(**r) for r in (job.pending_raw_relationships or [])]

        from backend.graph.operations import CampaignGraphOps
        from backend.core.database import neo4j_session
        from backend.graph.schema import RelationshipType as RT

        graph_ops = CampaignGraphOps()
        session_id = job.pending_session_id or ""
        campaign_id = job.pending_campaign_id
        entities_created = 0

        # MERGE each entity (create if missing, find if exists) and always get graph_id
        for entity in entities:
            try:
                with neo4j_session() as db:
                    result = db.run(
                        """
                        MERGE (e:Entity {name: $name, entity_type: $etype})
                        ON CREATE SET e.id = $id,
                                      e.source = 'transcript_extraction',
                                      e.confidence = $conf,
                                      e.first_session = $session_id,
                                      e.plane = 'campaign',
                                      e.created_at = datetime(),
                                      e.updated_at = datetime()
                        ON MATCH SET e.plane = coalesce(e.plane, 'campaign')
                        RETURN e.id AS id
                        """,
                        name=entity.normalized_name,
                        etype=entity.entity_type.value,
                        id=f"te_{uuid.uuid4().hex[:10]}",
                        conf=entity.confidence,
                        session_id=session_id,
                    )
                    record = result.single()
                    if record:
                        entity.graph_id = record["id"]
                        entities_created += 1

                        # Link to session
                        graph_ops.create_relationship(
                            source_id=entity.graph_id,
                            target_id=session_id,
                            relationship_type=RT.OCCURRED_IN,
                        )

                        # Link to campaign
                        if campaign_id:
                            graph_ops.create_relationship(
                                source_id=entity.graph_id,
                                target_id=campaign_id,
                                relationship_type=RT.BELONGS_TO,
                            )
            except Exception as e:
                logger.warning("Failed to merge entity %s: %s", entity.normalized_name, e)

        # Create relationships using resolved graph_ids
        relationships_created = 0
        entity_lookup: dict[str, str] = {}
        for entity in entities:
            if entity.graph_id:
                entity_lookup[entity.normalized_name.lower()] = entity.graph_id

        for rel in relationships:
            source_id = entity_lookup.get(rel.source_entity_name.lower())
            target_id = entity_lookup.get(rel.target_entity_name.lower())
            if source_id and target_id:
                try:
                    graph_ops.create_relationship(
                        source_id=source_id,
                        target_id=target_id,
                        relationship_type=rel.relationship_type,
                        properties={
                            "confidence": rel.confidence,
                            "evidence": rel.evidence[:200] if rel.evidence else "",
                            "session_id": session_id,
                        },
                    )
                    relationships_created += 1
                except Exception:
                    pass
            else:
                logger.warning(
                    "Skipped relationship %s -> %s: source=%s target=%s",
                    rel.source_entity_name, rel.target_entity_name,
                    bool(source_id), bool(target_id),
                )

        # Build final transcript result
        job.transcript_result = {
            "session_id": session_id,
            "session_number": job.pending_session_number,
            "campaign_id": job.pending_campaign_id,
            "segments_processed": job.pending_segments_processed or 0,
            "entities_extracted": len(job.pending_entities or []),
            "entities_created": entities_created,
            "relationships_extracted": len(job.pending_relationships or []),
            "relationships_created": relationships_created,
            "entity_counts": job.pending_entity_counts or {},
            "processing_time_ms": job.pending_processing_time_ms or 0,
            "errors": job.pending_errors or [],
            "entities": job.pending_entities or [],
            "relationships": job.pending_relationships or [],
        }
        job.phase = AudioJobPhase.COMPLETED

        logger.info(
            "Entities confirmed for job %s: %d entities, %d relationships written to graph",
            job_id,
            entities_created,
            relationships_created,
        )

        # Save transcript history
        try:
            _save_transcript_history(
                job,
                job.pending_transcript_text or "",
                job.pending_speaker_defs or [],
                job.pending_session_number,
                job.pending_campaign_id,
            )
        except Exception as save_err:
            logger.error("Failed to save transcript history for job %s: %s", job_id, save_err)

        return {
            "job_id": job_id,
            "phase": AudioJobPhase.COMPLETED.value,
            "entities_created": entities_created,
            "relationships_created": relationships_created,
        }

    except Exception as e:
        logger.error("Entity confirmation failed for job %s: %s", job_id, e)
        job.phase = AudioJobPhase.FAILED
        job.error = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to confirm entities: {e}")


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


@router.get("/transcripts")
async def list_transcripts():
    """List saved transcript history, sorted by most recent first."""
    transcript_dir = settings.transcript_dir
    if not transcript_dir.exists():
        return {"transcripts": []}

    items = []
    for fp in transcript_dir.glob("*.json"):
        try:
            data = json.loads(fp.read_text())
            items.append({
                "job_id": data.get("job_id"),
                "filename": data.get("filename"),
                "completed_at": data.get("completed_at"),
                "session_number": data.get("session_number"),
                "total_duration": data.get("total_duration"),
                "segment_count": data.get("segment_count"),
                "entities_extracted": (
                    data.get("transcript_result", {}).get("entities_extracted")
                    if data.get("transcript_result")
                    else None
                ),
                "_mtime": fp.stat().st_mtime,
            })
        except Exception:
            logger.warning("Skipping invalid transcript file: %s", fp)

    items.sort(key=lambda x: x.get("_mtime", 0), reverse=True)
    for item in items:
        item.pop("_mtime", None)

    return {"transcripts": items}


@router.get("/transcripts/{job_id}")
async def get_transcript(job_id: str):
    """Return the full saved transcript for a given job."""
    filepath = settings.transcript_dir / f"{job_id}.json"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")

    try:
        return json.loads(filepath.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read transcript: {e}")
