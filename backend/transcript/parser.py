"""Transcript parser for various formats."""

import json
import re
from pathlib import Path
from typing import Optional

from backend.transcript.models import (
    ParsedTranscript,
    TranscriptSegment,
    Speaker,
    SpeakerRole,
)


class TranscriptParser:
    """Parse transcripts from various formats."""

    # Common DM indicators
    DM_INDICATORS = {"dm", "dungeon master", "gm", "game master", "narrator"}

    # Patterns for different formats
    DISCORD_PATTERN = re.compile(
        r"^(?P<timestamp>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M\s*)?"
        r"(?P<speaker>[^:]+):\s*(?P<text>.+)$",
        re.MULTILINE,
    )

    # Pattern: "Speaker: text" or "Speaker (Character): text"
    SIMPLE_PATTERN = re.compile(
        r"^(?P<speaker>[^:\n]+?)(?:\s*\((?P<character>[^)]+)\))?\s*:\s*(?P<text>.+)$",
        re.MULTILINE,
    )

    # Pattern for timestamps like [00:00:00] or (00:00)
    TIMESTAMP_PATTERN = re.compile(
        r"^\s*[\[\(]?(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\s*[\]\)]?\s*"
        r"(?P<speaker>[^:\n]+?):\s*(?P<text>.+)$",
        re.MULTILINE,
    )

    def __init__(self):
        """Initialize the parser."""
        self.known_speakers: dict[str, Speaker] = {}

    def parse(
        self,
        content: str,
        format_hint: Optional[str] = None,
        speakers: Optional[list[dict]] = None,
    ) -> ParsedTranscript:
        """Parse transcript content.

        Args:
            content: The transcript text content.
            format_hint: Optional hint about format (json, discord, plain).
            speakers: Optional list of known speakers with roles.

        Returns:
            ParsedTranscript object.
        """
        # Initialize known speakers
        if speakers:
            for sp in speakers:
                speaker = Speaker(
                    name=sp.get("name", "Unknown"),
                    role=SpeakerRole(sp.get("role", "unknown")),
                    character_name=sp.get("character_name"),
                    aliases=sp.get("aliases", []),
                )
                self.known_speakers[speaker.name.lower()] = speaker

        # Detect format if not provided
        if format_hint is None:
            format_hint = self._detect_format(content)

        # Parse based on format
        if format_hint == "json":
            return self._parse_json(content)
        elif format_hint == "discord":
            return self._parse_discord(content)
        elif format_hint == "timestamped":
            return self._parse_timestamped(content)
        else:
            return self._parse_plain(content)

    def parse_file(
        self,
        filepath: str | Path,
        speakers: Optional[list[dict]] = None,
    ) -> ParsedTranscript:
        """Parse a transcript file.

        Args:
            filepath: Path to the transcript file.
            speakers: Optional list of known speakers.

        Returns:
            ParsedTranscript object.
        """
        path = Path(filepath)

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Detect format from extension
        format_hint = None
        if path.suffix.lower() == ".json":
            format_hint = "json"

        return self.parse(content, format_hint, speakers)

    def _detect_format(self, content: str) -> str:
        """Detect the format of the transcript."""
        content_stripped = content.strip()

        # Check for JSON
        if content_stripped.startswith("{") or content_stripped.startswith("["):
            try:
                json.loads(content_stripped)
                return "json"
            except json.JSONDecodeError:
                pass

        # Check for Discord-style timestamps
        if re.search(r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}", content):
            return "discord"

        # Check for timestamp prefixes
        if re.search(r"^\s*[\[\(]?\d{1,2}:\d{2}", content, re.MULTILINE):
            return "timestamped"

        # Check for simple "Speaker: text" format
        if re.search(r"^[^:\n]+:\s+.+$", content, re.MULTILINE):
            return "simple"

        return "plain"

    def _parse_json(self, content: str) -> ParsedTranscript:
        """Parse JSON-formatted transcript."""
        data = json.loads(content)
        segments = []
        speakers_found = {}

        # Handle array of turns
        if isinstance(data, list):
            turns = data
        elif isinstance(data, dict):
            turns = data.get("turns", data.get("segments", data.get("messages", [])))
        else:
            turns = []

        for i, turn in enumerate(turns):
            speaker_name = turn.get("speaker", turn.get("name", turn.get("user", "Unknown")))
            text = turn.get("text", turn.get("content", turn.get("message", "")))
            timestamp = turn.get("timestamp", turn.get("time"))
            character = turn.get("character", turn.get("character_name"))

            if not text:
                continue

            # Track speaker
            speaker_lower = speaker_name.lower()
            if speaker_lower not in speakers_found:
                role = self._infer_role(speaker_name, turn.get("role"))
                speakers_found[speaker_lower] = Speaker(
                    name=speaker_name,
                    role=role,
                    character_name=character,
                )

            segments.append(
                TranscriptSegment(
                    index=i,
                    speaker=speaker_name,
                    speaker_role=speakers_found[speaker_lower].role,
                    text=text,
                    timestamp=str(timestamp) if timestamp else None,
                    character_name=character,
                )
            )

        return ParsedTranscript(
            segments=segments,
            speakers=list(speakers_found.values()),
            raw_text=content,
            source_format="json",
        )

    def _parse_discord(self, content: str) -> ParsedTranscript:
        """Parse Discord-style chat logs."""
        segments = []
        speakers_found = {}

        for i, match in enumerate(self.DISCORD_PATTERN.finditer(content)):
            speaker_name = match.group("speaker").strip()
            text = match.group("text").strip()
            timestamp = match.group("timestamp")

            if not text:
                continue

            # Track speaker
            speaker_lower = speaker_name.lower()
            if speaker_lower not in speakers_found:
                role = self._infer_role(speaker_name)
                speakers_found[speaker_lower] = Speaker(
                    name=speaker_name,
                    role=role,
                )

            segments.append(
                TranscriptSegment(
                    index=i,
                    speaker=speaker_name,
                    speaker_role=speakers_found[speaker_lower].role,
                    text=text,
                    timestamp=timestamp.strip() if timestamp else None,
                )
            )

        return ParsedTranscript(
            segments=segments,
            speakers=list(speakers_found.values()),
            raw_text=content,
            source_format="discord",
        )

    def _parse_timestamped(self, content: str) -> ParsedTranscript:
        """Parse transcript with timestamp prefixes."""
        segments = []
        speakers_found = {}

        for i, match in enumerate(self.TIMESTAMP_PATTERN.finditer(content)):
            speaker_name = match.group("speaker").strip()
            text = match.group("text").strip()
            timestamp = match.group("timestamp")

            if not text:
                continue

            # Check for character in parentheses
            character = None
            char_match = re.match(r"(.+?)\s*\(([^)]+)\)", speaker_name)
            if char_match:
                speaker_name = char_match.group(1).strip()
                character = char_match.group(2).strip()

            # Track speaker
            speaker_lower = speaker_name.lower()
            if speaker_lower not in speakers_found:
                role = self._infer_role(speaker_name)
                speakers_found[speaker_lower] = Speaker(
                    name=speaker_name,
                    role=role,
                    character_name=character,
                )

            segments.append(
                TranscriptSegment(
                    index=i,
                    speaker=speaker_name,
                    speaker_role=speakers_found[speaker_lower].role,
                    text=text,
                    timestamp=timestamp,
                    character_name=character,
                )
            )

        return ParsedTranscript(
            segments=segments,
            speakers=list(speakers_found.values()),
            raw_text=content,
            source_format="timestamped",
        )

    def _parse_plain(self, content: str) -> ParsedTranscript:
        """Parse plain text transcript with Speaker: format."""
        segments = []
        speakers_found = {}

        # Try to find "Speaker: text" patterns
        matches = list(self.SIMPLE_PATTERN.finditer(content))

        if matches:
            for i, match in enumerate(matches):
                speaker_name = match.group("speaker").strip()
                text = match.group("text").strip()
                character = match.group("character")

                if not text or len(speaker_name) > 50:  # Skip if speaker too long
                    continue

                # Track speaker
                speaker_lower = speaker_name.lower()
                if speaker_lower not in speakers_found:
                    role = self._infer_role(speaker_name)
                    speakers_found[speaker_lower] = Speaker(
                        name=speaker_name,
                        role=role,
                        character_name=character.strip() if character else None,
                    )

                segments.append(
                    TranscriptSegment(
                        index=i,
                        speaker=speaker_name,
                        speaker_role=speakers_found[speaker_lower].role,
                        text=text,
                        character_name=character.strip() if character else None,
                    )
                )
        else:
            # No speaker pattern found, treat as single block
            segments.append(
                TranscriptSegment(
                    index=0,
                    text=content.strip(),
                )
            )

        return ParsedTranscript(
            segments=segments,
            speakers=list(speakers_found.values()),
            raw_text=content,
            source_format="plain",
        )

    def _infer_role(
        self,
        speaker_name: str,
        explicit_role: Optional[str] = None,
    ) -> SpeakerRole:
        """Infer the role of a speaker."""
        # Check explicit role
        if explicit_role:
            role_lower = explicit_role.lower()
            if role_lower in ("dm", "dungeon master", "gm", "game master"):
                return SpeakerRole.DM
            elif role_lower == "player":
                return SpeakerRole.PLAYER

        # Check known speakers
        speaker_lower = speaker_name.lower().strip()
        if speaker_lower in self.known_speakers:
            return self.known_speakers[speaker_lower].role

        # Check DM indicators
        if speaker_lower in self.DM_INDICATORS:
            return SpeakerRole.DM

        # Check for "Player X" pattern
        if speaker_lower.startswith("player"):
            return SpeakerRole.PLAYER

        return SpeakerRole.UNKNOWN
