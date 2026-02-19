"""Convert diarized transcription to the format expected by TranscriptProcessor."""

from backend.audio.models import (
    DiarizedTranscript,
    SpeakerMappingEntry,
)


class DiarizedTranscriptConverter:
    """Converts diarized segments + speaker mappings into transcript text
    matching TranscriptParser.TIMESTAMP_PATTERN and speaker defs for
    TranscriptProcessor.process().
    """

    def __init__(
        self,
        transcript: DiarizedTranscript,
        mappings: list[SpeakerMappingEntry],
    ):
        self.transcript = transcript
        self.mappings = mappings
        # Build lookup: speaker_index -> mapping
        self._map = {m.speaker_index: m for m in mappings}

    def to_transcript_text(self) -> str:
        """Produce timestamped transcript text matching TIMESTAMP_PATTERN.

        Format: [HH:MM:SS] PlayerName (CharacterName): text
        For DM:  [HH:MM:SS] DM: text

        Returns:
            Multi-line string ready for TranscriptParser.
        """
        lines: list[str] = []

        for seg in self.transcript.segments:
            ts = self._format_timestamp(seg.start)
            label = self._speaker_label(seg.speaker)
            lines.append(f"[{ts}] {label}: {seg.text}")

        return "\n".join(lines)

    def to_speaker_defs(self) -> list[dict]:
        """Produce speaker definition dicts for TranscriptProcessor.process(speakers=...).

        Each dict has: name, role, character_name, aliases.

        Returns:
            List of speaker dicts.
        """
        defs: list[dict] = []

        for m in self.mappings:
            if m.role == "dm":
                defs.append({
                    "name": m.player_name or "DM",
                    "role": "dm",
                    "character_name": None,
                    "aliases": ["DM", "Dungeon Master"],
                })
            else:
                entry: dict = {
                    "name": m.player_name,
                    "role": "player",
                    "character_name": m.character_name,
                    "aliases": [],
                }
                # Add character name as alias if present
                if m.character_name:
                    entry["aliases"].append(m.character_name)
                defs.append(entry)

        return defs

    def _speaker_label(self, speaker_index: int) -> str:
        """Build the speaker label for a transcript line.

        DM -> "DM"
        Player with character -> "PlayerName (CharacterName)"
        Player without character -> "PlayerName"
        Unmapped -> "Speaker N"
        """
        mapping = self._map.get(speaker_index)
        if mapping is None:
            return f"Speaker {speaker_index}"

        if mapping.role == "dm":
            return mapping.player_name or "DM"

        if mapping.character_name:
            return f"{mapping.player_name} ({mapping.character_name})"

        return mapping.player_name

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Convert seconds to HH:MM:SS format."""
        total = int(seconds)
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
