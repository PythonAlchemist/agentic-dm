"""Deepgram-based audio transcriber with speaker diarization."""

import logging
from collections import defaultdict
from pathlib import Path

from deepgram import DeepgramClient

from backend.audio.models import (
    DiarizedSegment,
    DiarizedTranscript,
    SpeakerSample,
)
from backend.core.config import settings

logger = logging.getLogger(__name__)

SAMPLES_PER_SPEAKER = 5


class DeepgramTranscriber:
    """Wraps Deepgram SDK for transcription with speaker diarization."""

    def __init__(self, api_key: str | None = None):
        key = api_key or settings.deepgram_api_key
        if not key:
            raise ValueError(
                "Deepgram API key required. Set DEEPGRAM_API_KEY in .env"
            )
        self.client = DeepgramClient(api_key=key)

    async def transcribe_file(self, filepath: str | Path) -> DiarizedTranscript:
        """Transcribe an audio file with speaker diarization.

        Args:
            filepath: Path to the audio file.

        Returns:
            DiarizedTranscript with segments and speaker samples.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Audio file not found: {filepath}")

        with open(filepath, "rb") as f:
            buffer_data = f.read()

        logger.info("Sending %s to Deepgram for transcription", filepath.name)

        response = self.client.listen.v1.media.transcribe_file(
            request=buffer_data,
            model="nova-2",
            diarize=True,
            utterances=True,
            smart_format=True,
            punctuate=True,
        )

        return self._parse_response(response)

    def _parse_response(self, response) -> DiarizedTranscript:
        """Parse Deepgram ListenV1Response into DiarizedTranscript."""
        segments: list[DiarizedSegment] = []
        speaker_utterances: dict[int, list[DiarizedSegment]] = defaultdict(list)

        # Prefer word-level diarization for finer speaker boundaries
        segments, speaker_utterances = self._segments_from_words(response)

        # Fall back to utterances if word-level data is unavailable
        if not segments:
            utterances_container = getattr(response.results, "utterances", None)
            utterances = []
            if utterances_container:
                utterances = getattr(utterances_container, "utterances", utterances_container) or []

            for utt in utterances:
                speaker = getattr(utt, "speaker", 0) or 0
                text = getattr(utt, "transcript", "").strip()
                start = getattr(utt, "start", 0.0) or 0.0
                end = getattr(utt, "end", 0.0) or 0.0
                confidence = getattr(utt, "confidence", 0.0) or 0.0

                if not text:
                    continue

                seg = DiarizedSegment(
                    speaker=speaker,
                    text=text,
                    start=start,
                    end=end,
                    confidence=confidence,
                )
                segments.append(seg)
                speaker_utterances[speaker].append(seg)

        # Build speaker samples
        speaker_samples = []
        for spk_idx in sorted(speaker_utterances.keys()):
            utts = speaker_utterances[spk_idx]
            total_dur = sum(s.end - s.start for s in utts)
            samples = [s.text for s in utts[:SAMPLES_PER_SPEAKER]]

            speaker_samples.append(
                SpeakerSample(
                    speaker_index=spk_idx,
                    utterance_count=len(utts),
                    total_duration=round(total_dur, 2),
                    sample_texts=samples,
                )
            )

        # Total duration from metadata
        total_duration = 0.0
        metadata = getattr(response, "metadata", None)
        if metadata and hasattr(metadata, "duration"):
            total_duration = metadata.duration or 0.0
        elif segments:
            total_duration = segments[-1].end

        return DiarizedTranscript(
            segments=segments,
            speaker_count=len(speaker_samples),
            speaker_samples=speaker_samples,
            total_duration=round(total_duration, 2),
            metadata={"model": "nova-2"},
        )

    def _segments_from_words(self, response):
        """Build segments from word-level speaker labels when utterances are unavailable."""
        segments: list[DiarizedSegment] = []
        speaker_utterances: dict[int, list[DiarizedSegment]] = defaultdict(list)

        channels_container = getattr(response.results, "channels", None)
        if not channels_container:
            return segments, speaker_utterances

        # Handle both list and wrapper object
        channels = getattr(channels_container, "channels", channels_container) or []
        if not channels:
            return segments, speaker_utterances

        alternatives = getattr(channels[0], "alternatives", []) or []
        if not alternatives:
            return segments, speaker_utterances

        words = getattr(alternatives[0], "words", []) or []
        if not words:
            return segments, speaker_utterances

        # Group consecutive words by speaker
        current_speaker = getattr(words[0], "speaker", 0) or 0
        current_words = [words[0]]

        for word in words[1:]:
            spk = getattr(word, "speaker", 0) or 0
            if spk != current_speaker:
                seg = self._words_to_segment(current_speaker, current_words)
                segments.append(seg)
                speaker_utterances[current_speaker].append(seg)
                current_speaker = spk
                current_words = [word]
            else:
                current_words.append(word)

        # Final group
        if current_words:
            seg = self._words_to_segment(current_speaker, current_words)
            segments.append(seg)
            speaker_utterances[current_speaker].append(seg)

        return segments, speaker_utterances

    @staticmethod
    def _words_to_segment(speaker: int, words: list) -> DiarizedSegment:
        """Combine a list of word objects into a single segment."""
        text = " ".join(
            getattr(w, "word", getattr(w, "punctuated_word", ""))
            for w in words
        )
        start = getattr(words[0], "start", 0.0) or 0.0
        end = getattr(words[-1], "end", 0.0) or 0.0
        avg_conf = sum(getattr(w, "confidence", 0.0) or 0.0 for w in words) / max(len(words), 1)

        return DiarizedSegment(
            speaker=speaker,
            text=text.strip(),
            start=start,
            end=end,
            confidence=round(avg_conf, 3),
        )
