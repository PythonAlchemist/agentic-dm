"""Pulling one entity back out of another it was wrongly merged into.

`merge_duplicates` folds two nodes and the survivor keeps the loser's aliases,
so when the fold was wrong there is nothing left to un-fold. These cover the
part that decides WHICH sections move, which is where the interesting mistake
is available.
"""

from backend.scripts.split_entity import names_present, plan


def _row(index: int, text: str) -> dict:
    return {
        "mid": f"kftgv:prisoner-13:axebreaker-dwarves@kftgv:prisoner-13#{index}",
        "props": {"occurrences": 1},
        "sec": f"kftgv:prisoner-13#{index}",
        "text": text,
    }


SURFACES = ["Varrin", "Varrin Axebreaker"]
KEPT = ["Axebreaker dwarves", "Clan Axebreaker"]


class TestDecidingWhichSectionsMove:
    def test_a_section_naming_only_the_person_moves(self):
        grouped = plan([_row(7, "Varrin has sent word to his agents.")], SURFACES, KEPT)
        assert [r["sec"] for r in grouped["moves"]] == ["kftgv:prisoner-13#7"]
        assert grouped["both"] == [] and grouped["stays"] == []

    def test_a_section_naming_only_the_clan_stays(self):
        grouped = plan([_row(1, "The Axebreaker dwarves keep a stronghold.")], SURFACES, KEPT)
        assert [r["sec"] for r in grouped["stays"]] == ["kftgv:prisoner-13#1"]
        assert grouped["moves"] == []

    def test_a_section_naming_both_is_not_taken_from_either(self):
        """THE CASE `display_name` CANNOT SEE. A mention is one node per
        (entity, section), so a section naming the man and the clan kept only
        one of the two spellings -- and four of the twelve did. Deciding from
        the stored spelling moves seven sections and leaves four behind."""
        grouped = plan(
            [_row(2, "Clan Axebreaker sent Varrin to hire the characters.")],
            SURFACES, KEPT,
        )
        assert [r["sec"] for r in grouped["both"]] == ["kftgv:prisoner-13#2"]
        assert grouped["moves"] == [] and grouped["stays"] == []

    def test_a_section_naming_neither_is_left_alone(self):
        """Some other spelling put that mention there, and this pass has no
        opinion about it. Claiming it for either side would be a guess."""
        grouped = plan([_row(9, "A quiet corridor, and nobody in it.")], SURFACES, KEPT)
        assert [r["sec"] for r in grouped["neither"]] == ["kftgv:prisoner-13#9"]

    def test_every_row_lands_in_exactly_one_bucket(self):
        rows = [
            _row(0, "Varrin Axebreaker hires them."),
            _row(1, "The Axebreaker dwarves wait."),
            _row(2, "Clan Axebreaker sent Varrin."),
            _row(9, "Nothing is named here."),
        ]
        grouped = plan(rows, SURFACES, KEPT)
        landed = [r["sec"] for bucket in grouped.values() for r in bucket]
        assert sorted(landed) == sorted(r["sec"] for r in rows)
        assert len(landed) == len(set(landed))

    def test_missing_text_is_not_a_crash(self):
        """A section with no stored text names nothing, which is what the
        `neither` bucket is for."""
        row = _row(3, "")
        row["text"] = None
        assert plan([row], SURFACES, KEPT)["neither"] == [row]


class TestALongNameBeatsAShortOneInsideIt:
    """A plain substring test makes a short name match inside a long one.
    `Xeluan` is contained in `Order of Xeluan` and in `Shard of Xeluan`, so
    splitting the giant out of his own order claimed all twenty of the order's
    sections -- including the five that only ever write the order's name."""

    SURFACES = ["Xeluan"]
    KEPT = ["Order of Xeluan", "Shard of Xeluan"]

    def test_the_order_alone_is_not_the_giant(self):
        assert names_present(
            "The Order of Xeluan keeps the tomb.", self.SURFACES, self.KEPT
        ) == (False, True)

    def test_the_giant_alone_is_not_the_order(self):
        assert names_present(
            "Xeluan pledged his life.", self.SURFACES, self.KEPT
        ) == (True, False)

    def test_a_text_using_both_credits_both(self):
        assert names_present(
            "Xeluan founded it; the Order of Xeluan remains.", self.SURFACES, self.KEPT
        ) == (True, True)

    def test_the_shard_does_not_make_the_giant_present(self):
        """Two different long names both contain the short one."""
        assert names_present(
            "The Shard of Xeluan is obsidian.", self.SURFACES, self.KEPT
        ) == (False, True)

    def test_neither_is_neither(self):
        assert names_present("A quiet tomb.", self.SURFACES, self.KEPT) == (False, False)

    def test_case_does_not_decide_it(self):
        assert names_present("xeluan walked.", self.SURFACES, self.KEPT) == (True, False)
