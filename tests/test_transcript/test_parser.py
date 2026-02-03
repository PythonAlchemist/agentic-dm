"""Tests for transcript parser."""

import pytest

from backend.transcript.parser import TranscriptParser
from backend.transcript.models import SpeakerRole


class TestTranscriptParser:
    """Test transcript parsing."""

    @pytest.fixture
    def parser(self):
        """Create a parser instance."""
        return TranscriptParser()

    def test_parse_simple_format(self, parser):
        """Test parsing simple Speaker: text format."""
        transcript = """
DM: As you enter the tavern, you see a grizzled dwarf at the bar.
Alice: I approach the dwarf and order an ale.
DM: The dwarf eyes you suspiciously.
Bob: I'll keep watch by the door.
        """

        result = parser.parse(transcript)

        assert result.segment_count == 4
        assert result.speaker_count >= 2

        # Check DM was identified
        dm_segments = result.get_dm_segments()
        assert len(dm_segments) == 2

    def test_parse_with_character_names(self, parser):
        """Test parsing with Player (Character) format."""
        transcript = """
DM: The dragon roars!
Player 1 (Aria): I cast Fireball!
Player 2 (Grimlock): I charge forward with my axe!
        """

        result = parser.parse(transcript)

        assert result.segment_count == 3

        # Check character names were extracted
        characters = [s.character_name for s in result.segments if s.character_name]
        assert "Aria" in characters
        assert "Grimlock" in characters

    def test_parse_json_format(self, parser):
        """Test parsing JSON formatted transcript."""
        transcript = """
        [
            {"speaker": "DM", "text": "You enter the dungeon."},
            {"speaker": "Alice", "role": "player", "text": "I light a torch."},
            {"speaker": "DM", "text": "The walls are covered in cobwebs."}
        ]
        """

        result = parser.parse(transcript, format_hint="json")

        assert result.segment_count == 3
        assert result.source_format == "json"

    def test_parse_json_with_metadata(self, parser):
        """Test parsing JSON with additional fields."""
        transcript = """
        {
            "turns": [
                {"speaker": "DM", "text": "Roll initiative!", "timestamp": "00:05:00"},
                {"speaker": "Thorin", "character": "Thorin", "text": "I got a 15!"}
            ]
        }
        """

        result = parser.parse(transcript)

        assert result.segment_count == 2
        assert result.segments[0].timestamp == "00:05:00"

    def test_parse_with_known_speakers(self, parser):
        """Test parsing with pre-defined speaker list."""
        transcript = """
Matt: The creature lunges at you!
Laura: I dodge!
Travis: I attack with my greatsword!
        """

        speakers = [
            {"name": "Matt", "role": "dm"},
            {"name": "Laura", "role": "player", "character_name": "Vex"},
            {"name": "Travis", "role": "player", "character_name": "Grog"},
        ]

        result = parser.parse(transcript, speakers=speakers)

        # Matt should be identified as DM
        matt_segments = [s for s in result.segments if s.speaker == "Matt"]
        assert len(matt_segments) == 1
        assert matt_segments[0].speaker_role == SpeakerRole.DM

    def test_parse_plain_text_no_speakers(self, parser):
        """Test parsing plain text without speaker markers."""
        transcript = """
        The party traveled through the forest for three days.
        They encountered several wolves along the way.
        Eventually they reached the ancient ruins.
        """

        result = parser.parse(transcript)

        # Should create single segment for unstructured text
        assert result.segment_count >= 1

    def test_detect_format_json(self, parser):
        """Test format detection for JSON."""
        json_content = '{"turns": [{"speaker": "DM", "text": "Hello"}]}'
        assert parser._detect_format(json_content) == "json"

    def test_detect_format_simple(self, parser):
        """Test format detection for simple format."""
        simple_content = "DM: Welcome to the game!\nPlayer: Thanks!"
        assert parser._detect_format(simple_content) == "simple"

    def test_infer_role_dm(self, parser):
        """Test DM role inference."""
        assert parser._infer_role("DM") == SpeakerRole.DM
        assert parser._infer_role("Dungeon Master") == SpeakerRole.DM
        assert parser._infer_role("GM") == SpeakerRole.DM

    def test_infer_role_player(self, parser):
        """Test player role inference."""
        assert parser._infer_role("Player 1") == SpeakerRole.PLAYER
        assert parser._infer_role("Player") == SpeakerRole.PLAYER

    def test_segment_properties(self, parser):
        """Test that segments have correct properties."""
        transcript = "DM: You see a goblin. It attacks!"

        result = parser.parse(transcript)

        assert len(result.segments) == 1
        segment = result.segments[0]
        assert segment.index == 0
        assert segment.speaker == "DM"
        assert "goblin" in segment.text
        assert segment.entities == []  # Not populated until NER runs


class TestParsedTranscript:
    """Test ParsedTranscript methods."""

    @pytest.fixture
    def parser(self):
        return TranscriptParser()

    def test_full_text(self, parser):
        """Test full_text property."""
        transcript = """
DM: First line.
Player: Second line.
DM: Third line.
        """

        result = parser.parse(transcript)

        full = result.full_text
        assert "First line" in full
        assert "Second line" in full
        assert "Third line" in full

    def test_get_segments_by_speaker(self, parser):
        """Test filtering segments by speaker."""
        transcript = """
DM: Welcome!
Alice: Hello!
DM: Let's begin.
Bob: Ready!
        """

        result = parser.parse(transcript)

        dm_segments = result.get_segments_by_speaker("DM")
        assert len(dm_segments) == 2

        alice_segments = result.get_segments_by_speaker("Alice")
        assert len(alice_segments) == 1
