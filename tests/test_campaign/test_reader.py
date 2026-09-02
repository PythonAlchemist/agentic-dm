"""What a DM is told the book says.

These rules lived between session handling and a response dict inside
`api/routes/homebrew.py`, so exercising one meant an HTTP call against a live
graph. They are not plumbing: they decide which of the book's sentences are
quoted back, and the route's own docstrings record two bugs that reached a DM
through them.
"""

from backend.campaign.reader import QUOTE_WINDOW, entity_card, sentences_at


class TestQuotingTheBookExactly:
    """Everything else the endpoint returns is the graph's own record. This is
    the book's words, and a paraphrase would be the one kind of sentence a DM
    has no way to check."""

    TEXT = "The road is long. Ireena waits at the mansion. Fog closes in."

    def test_it_quotes_the_sentence_the_name_sits_in(self):
        at = self.TEXT.index("Ireena")
        assert sentences_at(self.TEXT, [at]) == ["Ireena waits at the mansion."]

    def test_several_offsets_give_several_sentences(self):
        first = self.TEXT.index("road")
        second = self.TEXT.index("Fog")
        assert len(sentences_at(self.TEXT, [first, second])) == 2

    def test_the_same_sentence_twice_is_quoted_once(self):
        at = self.TEXT.index("Ireena")
        assert len(sentences_at(self.TEXT, [at, at + 1])) == 1

    def test_it_stops_at_the_limit(self):
        offsets = [0, self.TEXT.index("Ireena"), self.TEXT.index("Fog")]
        assert len(sentences_at(self.TEXT, offsets, limit=2)) == 2

    def test_an_offset_outside_the_text_is_skipped_not_clamped(self):
        """A clamp would quote the start of the section as though the name were
        there. The offsets come from a scan of a body that may since have been
        re-written."""
        assert sentences_at(self.TEXT, [9999]) == []
        assert sentences_at(self.TEXT, [-1]) == []

    def test_prose_with_no_full_stop_falls_back_to_a_window(self):
        """Headings and table rows often have none."""
        text = "Barovian Names " + "x" * 50 + " Ireena " + "y" * 50
        quote = sentences_at(text, [text.index("Ireena")])[0]
        assert "Ireena" in quote
        assert len(quote) <= QUOTE_WINDOW * 2 + 2

    def test_a_runaway_sentence_is_windowed_rather_than_quoted_whole(self):
        """A quote that runs on is worse than one that stops early."""
        text = "A. " + "word " * 400 + "Ireena " + "word " * 400 + "."
        quote = sentences_at(text, [text.index("Ireena")])[0]
        assert "Ireena" in quote
        assert len(quote) < len(text)

    def test_whitespace_is_collapsed_so_a_quote_reads_as_one_line(self):
        text = "The road\n\n   is  long. Ireena waits."
        assert sentences_at(text, [0])[0] == "The road is long."

    def test_no_offsets_is_no_quotes(self):
        assert sentences_at(self.TEXT, []) == []

    def test_an_empty_section_is_no_quotes(self):
        assert sentences_at("", [0]) == []


class TestTheEntityCard:
    def _row(self, **over):
        return {
            "entity_id": "cos:ireena", "name": "Ireena", "kind": "NPC",
            "plane": "canon", "role": None, "invented": None,
            "labels": ["Entity", "NPC"], "own_section": None,
            "named_by_book": None, "named_in": [],
            **over,
        }

    def test_the_bare_entity_label_is_dropped(self):
        """Every node has it and it says nothing."""
        assert entity_card(self._row())["labels"] == ["NPC"]

    def test_a_row_naming_no_section_is_dropped(self):
        """Cypher's `collect` of nothing is a row of nulls -- passing it
        through produced a citation to a section that does not exist."""
        card = entity_card(self._row(named_in=[{"section_id": None}]))
        assert card["named_in"] == []

    def test_a_real_mention_carries_its_sentence(self):
        card = entity_card(self._row(named_in=[{
            "section_id": "cos:x#1", "heading": "H", "plane": "canon",
            "text": "Ireena waits at the mansion.", "offsets": [0],
        }]))
        assert card["named_in"][0]["says"] == ["Ireena waits at the mansion."]

    def test_absent_means_the_book_names_it(self):
        """The property is only ever set to false, so absence is ordinary."""
        assert entity_card(self._row())["named_by_book"] is True

    def test_false_is_carried_through(self):
        assert entity_card(self._row(named_by_book=False))["named_by_book"] is False

    def test_it_is_always_a_bool(self):
        """A reader has no way to tell "not marked" from "not known"."""
        assert isinstance(entity_card(self._row())["named_by_book"], bool)

    def test_invented_parses_from_its_stored_json(self):
        card = entity_card(self._row(invented='["her surname"]'))
        assert card["invented"] == ["her surname"]

    def test_no_invented_is_an_empty_list_not_none(self):
        assert entity_card(self._row())["invented"] == []

    def test_the_row_is_not_mutated(self):
        """The caller's row is the driver's, and reusing it after this should
        not surprise anybody."""
        row = self._row(labels=["Entity", "NPC"])
        entity_card(row)
        assert row["labels"] == ["Entity", "NPC"]
