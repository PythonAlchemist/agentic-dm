"""Naming, on the write that makes them, the entities the chapter never says.

154 of these reached the graph unremarked. `mention_counts` could not show
them: it is built from a Counter over the mentions, so an entity that got none
is simply absent from the list a writer reads. They accumulated for as long as
the pipeline ran, and were found by counting the graph a year later.

Keeping them is the DM's ruling and is fine. Keeping them SILENTLY is the part
this closes.
"""

from backend.canon.writer import WriteNode, _minted_without_mention


class _Mention:
    def __init__(self, entity_id):
        self.entity_id = entity_id


def _node(entity_id, name):
    return WriteNode(id=entity_id, name=name, entity_types=("ITEM",),
                     chapter_slug="ch")


class TestTheZeroTheCensusCannotShow:
    def test_an_entity_no_mention_names_is_reported(self):
        """`Closet 1` -- a name the extractor wrote for something the book only
        describes."""
        found = _minted_without_mention(
            [_node("b:ch:closet-1", "Closet 1")], [])
        assert found == ["Closet 1"]

    def test_an_entity_the_prose_names_is_not(self):
        found = _minted_without_mention(
            [_node("b:ch:strahd", "Strahd")], [_Mention("b:ch:strahd")])
        assert found == []

    def test_only_the_silent_ones_come_back(self):
        """`Spellbook` is the other half: a common noun the extractor
        title-cased, which the scan then correctly refuses to match in
        lowercase prose."""
        found = _minted_without_mention(
            [_node("b:ch:strahd", "Strahd"), _node("b:ch:spellbook", "Spellbook")],
            [_Mention("b:ch:strahd")],
        )
        assert found == ["Spellbook"]

    def test_it_is_sorted_so_two_runs_diff_as_the_book(self):
        found = _minted_without_mention(
            [_node("b:ch:z", "Zoo"), _node("b:ch:a", "Amethyst")], [])
        assert found == ["Amethyst", "Zoo"]

    def test_several_mentions_of_one_entity_still_clear_it(self):
        found = _minted_without_mention(
            [_node("b:ch:e", "E")], [_Mention("b:ch:e"), _Mention("b:ch:e")])
        assert found == []

    def test_a_mention_of_something_this_write_did_not_mint_is_ignored(self):
        """The scan reads every entity the graph knows, not only this
        chapter's, so mentions of other chapters' entities arrive here and say
        nothing about what this write minted."""
        found = _minted_without_mention(
            [_node("b:ch:mine", "Mine")], [_Mention("b:other:theirs")])
        assert found == ["Mine"]

    def test_minting_nothing_reports_nothing(self):
        assert _minted_without_mention([], []) == []
