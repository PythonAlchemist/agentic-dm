"""Turn a parsed recording into graph rows, without inventing anything.

WHAT THIS USED TO DO. 501 lines that ran an LLM NER pipeline over four hours of
table talk with `create_missing_entities=True`, wrote `:Entity` nodes for every
name it thought it saw, wrote `RelationshipType` edges for every relationship
it thought it heard, and minted `session_<uuid4>` ids carrying no campaign --
so its debris was invisible even to the orphan check, which filters on
`campaign IS NOT NULL`.

Each of those is the same mistake in a different place: the least reliable
prose in the system was given the most trusted write path in it. A DM must be
able to tell what the published book says from what a model invented, and a
model reading a recording and creating entities from it puts the two in the
same store with nothing to separate them.

WHAT IT DOES NOW. Parses -- `parser.py` is unchanged and good, and detecting
Discord from Whisper from plain text is real work nobody should redo -- and
hands the turns to `campaign/transcripts.py`, which writes campaign-plane
`:Section` nodes and scans them with the SAME matcher the book goes through.
A name the graph already knows becomes a mention; a name it does not know is
left in the prose where a DM can read it and decide.

THE CLASS AND ITS SIGNATURES SURVIVE because two callers depend on them: the
audio route's background task and `scripts/process_transcript.py`. Their
behaviour changes -- nothing is minted any more -- and that is the point, but
neither needed rewriting to get it.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from backend.core.database import neo4j_session
from backend.transcript.models import ParsedTranscript, ProcessingResult
from backend.transcript.parser import TranscriptParser

logger = logging.getLogger(__name__)


class TranscriptProcessor:
    """Parse a transcript and record what was said, for one table."""

    def __init__(self, ner_config=None, create_entities: bool = True,
                 create_relationships: bool = True):
        """The three old knobs, kept so callers construct unchanged.

        THEY NO LONGER TURN ANYTHING ON, and that is deliberate rather than an
        oversight: `create_entities=True` was the default, and a default that
        lets a recording mint entities is not a setting, it is a hole. A
        caller passing `True` here is asking for something this module will not
        do, and honouring it would mean keeping the pipeline this replaced.
        """
        self.parser = TranscriptParser()
        if create_entities or create_relationships:
            logger.info(
                "transcript: entities and relationships are no longer written "
                "from recordings; the text is stored and scanned for names the "
                "graph already knows")

    async def process(
        self,
        content: str,
        session_number: Optional[int] = None,
        campaign_id: Optional[str] = None,
        speakers: Optional[list[dict]] = None,
        format_hint: Optional[str] = None,
    ) -> ProcessingResult:
        start = time.time()
        parsed = self.parser.parse(content, format_hint, speakers)
        result = self._record(parsed, session_number, campaign_id)
        result.processing_time_ms = (time.time() - start) * 1000
        return result

    async def process_file(
        self,
        filepath: str | Path,
        session_number: Optional[int] = None,
        campaign_id: Optional[str] = None,
        speakers: Optional[list[dict]] = None,
    ) -> ProcessingResult:
        start = time.time()
        parsed = self.parser.parse_file(filepath, speakers)
        result = self._record(parsed, session_number, campaign_id)
        result.processing_time_ms = (time.time() - start) * 1000
        return result

    def _record(
        self,
        parsed: ParsedTranscript,
        session_number: Optional[int],
        campaign_id: Optional[str],
    ) -> ProcessingResult:
        """Store the turns against a session of this campaign.

        NO CAMPAIGN MEANS NO WRITE. A transcript is a transcript OF something;
        without a table there is nothing for it to be evidence about, and the
        old code's answer -- write it anyway under a fresh uuid -- is exactly
        how the graph accumulated sessions nobody could find or delete.
        """
        from backend.campaign import sessions, transcripts

        said = [
            transcripts.Said(
                speaker=segment.speaker or "",
                text=segment.text or "",
                role=getattr(segment.speaker_role, "value", "") or "",
            )
            for segment in parsed.segments
            if (segment.text or "").strip()
        ]

        result = ProcessingResult(
            session_id="",
            session_number=session_number,
            campaign_id=campaign_id,
            segments_processed=len(said),
        )
        if not campaign_id:
            result.errors.append(
                "no campaign: the transcript was parsed but not stored, "
                "because a recording of no table is evidence about nothing")
            return result

        with neo4j_session() as session:
            opened = session.execute_write(lambda tx: sessions.open_session(
                tx, slug=campaign_id, title="", number=session_number))
            result.session_id = opened["id"]
            stored = session.execute_write(lambda tx: transcripts.record(
                tx, slug=campaign_id, session=opened["id"],
                number=opened["number"], said=said))

        # `entities_created` AND `relationships_created` STAY ZERO BY
        # CONSTRUCTION, not by configuration. They are kept in the response so
        # a caller reading the old fields sees the answer rather than a
        # missing key: nothing was invented.
        result.entities_extracted = stored["mentions"]
        result.entity_counts = {
            "sections": stored["sections"],
            "mentions": stored["mentions"],
            "replaced": stored["replaced"],
        }
        return result

    def process_sync(self, *args, **kwargs) -> ProcessingResult:
        import asyncio

        return asyncio.run(self.process(*args, **kwargs))

    def process_file_sync(self, *args, **kwargs) -> ProcessingResult:
        import asyncio

        return asyncio.run(self.process_file(*args, **kwargs))
