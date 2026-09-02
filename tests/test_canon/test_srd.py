"""Reading the SRD, which says what it means in its own typography.

`read_spans` takes spans rather than a file, so every rule below is exercised
on four lines instead of on a 403-page PDF -- and the rules are what break.
"""

from backend.canon.srd import Span, clean, is_heading, read_spans

BODY = "Cambria"
HEAD = "GillSans-SemiBold"
STAT = "Calibri-Bold"
FOOT = "Calibri-Italic"


def span(text, font=BODY, size=9.8, page=1):
    return Span(text=text, font=font, size=size, page=page)


def h(text, level, page=1):
    return span(text, HEAD, {1: 25.9, 2: 18.0, 3: 13.9, 4: 12.0}[level], page)


class TestCleaningWhatTheTypesetterLeft:
    def test_the_spacing_artefact_becomes_one_space(self):
        assert clean("When\t\r \xa0you\t\r \xa0move,") == "When you move,"

    def test_three_hyphens_become_one(self):
        """A reader sees a smear; a person typing "3rd-level" finds nothing,
        which is the worse half."""
        assert clean("3rd-\xad‐‑level") == "3rd-level"

    def test_a_soft_hyphen_inside_a_word_is_removed(self):
        """It marks a place a word MAY break and is not part of the word."""
        assert clean("with\xadin") == "within"

    def test_curly_quotes_are_folded(self):
        assert clean("the deva’s weapon") == "the deva's weapon"


class TestTellingAHeadingFromFurniture:
    def test_the_four_levels_are_recognised(self):
        assert [is_heading(h("x", n)) for n in (1, 2, 3, 4)] == [1, 2, 3, 4]

    def test_a_page_number_is_not_a_heading(self):
        """It is set in the heading face, so the font alone would make every
        page number a heading called "96"."""
        assert is_heading(span("96", HEAD, 10.8)) == 0

    def test_prose_is_not_a_heading(self):
        assert is_heading(span("A bright streak flashes", BODY, 9.8)) == 0


class TestWhatCountsAsAnEntry:
    def _spells(self, *names, container="Spell Descriptions"):
        spans = [h("Spellcasting", 1), h(container, 2)]
        for name in names:
            spans += [h(name, 4), span("Prose about it.")]
        return read_spans(spans)

    def test_a_spell_under_the_right_container_is_one(self):
        found = self._spells("Fireball")
        assert [(e.name, e.kind) for e in found.entries] == [("Fireball", "SPELL")]

    def test_the_casting_rules_are_not_spells(self):
        """`Spellcasting` opens with the rules for casting -- `Bonus Action`,
        `Reactions` -- set at exactly the level a spell name uses. Without the
        container those become a hundred spells nobody can cast."""
        found = self._spells("Bonus Action", container="Casting a Spell")
        assert found.entries == []
        assert found.passed_over == 1

    def test_prose_lands_on_the_entry_it_follows(self):
        found = self._spells("Fireball")
        assert "Prose about it." in found.entries[0].text

    def test_a_heading_split_across_lines_is_one_entry(self):
        """Two spans at one level with no prose between. Read apart, the SRD
        gains a magic item called `Location`."""
        found = read_spans([
            h("Magic Items", 1), h("Magic Items A-Z", 2),
            h("Amulet of Proof against Detection and", 4),
            h("Location", 4),
            span("It protects you."),
        ])
        assert [e.name for e in found.entries] == [
            "Amulet of Proof against Detection and Location"]


class TestStatBlocksAreTypesetDifferently:
    """A monster's name is `Calibri-Bold` at 12pt and a spell's is
    `GillSans-SemiBold` at 12pt: the same size, a different system."""

    def test_a_stat_block_name_is_an_entry(self):
        found = read_spans([
            h("Monsters", 1), h("Monsters (A)", 2),
            span("Aboleth", STAT, 12.0), span("Armor Class 17"),
        ])
        assert [(e.name, e.kind) for e in found.entries] == [
            ("Aboleth", "MONSTER")]

    def test_a_table_caption_in_the_front_matter_is_not_a_monster(self):
        """The chapter opens with `Size Categories` and `Hit Dice by Size`,
        whose captions are set in the stat-block face."""
        found = read_spans([
            h("Monsters", 1),
            span("Size Categories", STAT, 12.0), span("Tiny 2 1/2 by 2 1/2 ft."),
        ])
        assert found.entries == [] and found.passed_over == 1

    def test_a_stat_block_face_outside_a_monster_chapter_is_ignored(self):
        found = read_spans([
            h("Equipment", 1), span("Longsword", STAT, 12.0), span("1d8"),
        ])
        assert found.entries == []


class TestWhatIsDroppedIsCounted:
    """Silent filtering has twice hidden a defect in this project for weeks."""

    def test_the_running_footer_is_dropped_and_counted(self):
        found = read_spans([span("Not for resale.", FOOT, 7.9)])
        assert found.dropped_footers == 1 and found.entries == []

    def test_page_numbers_are_dropped_and_counted(self):
        found = read_spans([span("101", HEAD, 10.8)])
        assert found.dropped_page_numbers == 1

    def test_chapters_are_reported(self):
        found = read_spans([h("Races", 1, page=3), h("Equipment", 1, page=62)])
        assert found.chapters == ["Races", "Equipment"]

    def test_a_title_wrapped_onto_two_lines_is_one_chapter(self):
        """`Appendix PH-A: Conditions` is set as two spans on one page."""
        found = read_spans([h("Appendix PH-A:", 1, page=358),
                            h("Conditions", 1, page=358)])
        assert found.chapters == ["Appendix PH-A: Conditions"]
