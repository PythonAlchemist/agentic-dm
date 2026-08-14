"""`:Artifact` -- the one hand-authored item label.

Items are otherwise flat. `Tome of Strahd` sits beside `oil lamp` and
`tinderbox`, and three of the flat set are the campaign's spine: the Tarokka
reading sends the party after them, and "where are the artifacts" is a question
a DM asks constantly.

AUTHORED, NEVER DERIVED. A location's rung can sometimes be read off the book's
own key convention -- `E5g` is mechanically a room inside `E5`. Nothing marks an
artifact that way, so the three are named by hand in the same seed the location
rungs live in, and nothing here infers one from a name substring: chapter 3's
`Holy Symbol` is a wooden sun nailed to a church wall, not the Holy Symbol of
Ravenkind.

ONE LABEL, AND NO DEFAULT. An item absent from the seed stays plain `:ITEM`.
There is no `:mundane`, because "mundane" is the absence of significance and is
honestly encoded as the absence of a label.

NOT A RUNG. The location rungs are a ladder -- a place wears exactly one, so
writing one REMOVEs the rest. `:Artifact` is orthogonal to that ladder and to
any item label that might come later, so nothing supersedes it, it supersedes
nothing, and the rung REMOVE must never reach it or the `:ITEM` beneath it.

Pure: `plan_write` never opens a connection. The labels that actually land are
pinned in `test_write_canon_neo4j.py`.
"""

import pytest
import yaml

from backend.canon.assembler import slugify
from backend.canon.gazetteer import Gazetteer, GazetteerEntry
from backend.canon.models import CandidateNode
from backend.canon.seed_loader import LOCATION_SUBTYPE_SEED, load_artifacts
from backend.canon.writer import LOCATION_SUBTYPE_LABELS, WriteNode, plan_write
from backend.graph.schema import ARTIFACT_LABEL, EntityType

SLUG = "introduction"

TAROKKA = ("Tome of Strahd", "Holy Symbol of Ravenkind", "Sunsword")


def gazetteer(*names: str) -> Gazetteer:
    return Gazetteer(
        [GazetteerEntry(name=n, entity_type="ITEM", wiki_category="c") for n in names]
    )


def node(name: str, entity_type: str = "ITEM", **kwargs) -> CandidateNode:
    return CandidateNode(name=name, entity_type=entity_type, chapter_slug=SLUG, **kwargs)


def plan(names: list[str], authored: set[str], entity_type: str = "ITEM"):
    """Plan a write of `names`, with `authored` naming the artifacts.

    The gazetteer admits every name, so a node missing from the result is a
    labelling decision rather than a name the wiki had never heard of.
    """
    nodes, _, _ = plan_write(
        [node(n, entity_type) for n in names],
        [],
        gazetteer(*names),
        SLUG,
        artifacts={slugify(a) for a in authored},
    )
    return {n.name: n for n in nodes}


class TestTheAuthoredItemsWearIt:
    def test_an_authored_item_is_an_artifact(self):
        written = plan(["Tome of Strahd"], {"Tome of Strahd"})

        assert written["Tome of Strahd"].artifact_label == ARTIFACT_LABEL

    @pytest.mark.parametrize("name", TAROKKA)
    def test_each_of_the_three_wears_it(self, name):
        written = plan([name], set(TAROKKA))

        assert written[name].artifact_label == ARTIFACT_LABEL

    def test_it_is_matched_on_the_slug_not_the_spelling(self):
        """`mint_id` slugs, so a curly and a straight apostrophe are one name and
        the seed must not need both spellings."""
        written = plan(["Tome  of   Strahd"], {"Tome of Strahd"})

        assert written["Tome  of   Strahd"].artifact_label == ARTIFACT_LABEL


class TestEverythingElseStaysPlain:
    """No default. An item nobody authored must look unauthored."""

    @pytest.mark.parametrize("name", ["Trapdoor", "oil lamp", "tinderbox"])
    def test_an_unauthored_item_gets_no_label(self, name):
        written = plan([name], set(TAROKKA))

        assert written[name].artifact_label == ""
        assert written[name].is_artifact is False

    def test_no_second_label_stands_in_for_mundane(self):
        """`:mundane` was considered and rejected: it is the absence of
        significance, and the honest encoding of that is no label at all."""
        written = plan(["oil lamp"], set(TAROKKA))

        assert written["oil lamp"].labels == ("ITEM",)

    def test_a_name_containing_an_authored_one_is_not_an_artifact(self):
        """Chapter 3's `Holy Symbol` is a wooden sun on a church wall. A
        substring match would make it the Holy Symbol of Ravenkind."""
        written = plan(["Holy Symbol"], {"Holy Symbol of Ravenkind"})

        assert written["Holy Symbol"].artifact_label == ""

    def test_a_name_contained_by_an_authored_one_is_not_either(self):
        written = plan(["Sunsword of the Dawn"], {"Sunsword"})

        assert written["Sunsword of the Dawn"].artifact_label == ""

    def test_an_authored_entry_for_a_non_item_confers_nothing(self):
        """`:Artifact` narrows `:ITEM`. A place or a person that happened to
        share the name is not standing on that shelf."""
        written = plan(["Sunsword"], {"Sunsword"}, entity_type="LOCATION")

        assert written["Sunsword"].artifact_label == ""

    def test_planning_without_a_seed_labels_nothing(self):
        """The default is the empty set, not "everything looks plausible"."""
        nodes, _, _ = plan_write(
            [node("Tome of Strahd")], [], gazetteer("Tome of Strahd"), SLUG
        )

        assert nodes[0].artifact_label == ""


class TestItemSurvivesTheLabel:
    """`:ITEM` is what makes "every object in the book" a one-word query, and
    `:Artifact` is an ADDITIONAL label rather than a replacement."""

    def test_the_item_type_is_still_there(self):
        written = plan(["Sunsword"], {"Sunsword"})

        assert "ITEM" in written["Sunsword"].labels

    def test_the_type_labels_do_not_gain_it(self):
        """Written apart from `labels` because the two are written differently.
        Folding it in would put it through `CANON_LABELS`, which would drop it."""
        written = plan(["Sunsword"], {"Sunsword"})

        assert ARTIFACT_LABEL not in written["Sunsword"].labels

    def test_a_disputed_type_that_includes_item_still_qualifies(self):
        """Two samples typing one node ITEM and LORE leave it wearing both, and
        the half of the disagreement that is an item is enough."""
        nodes, _, _ = plan_write(
            [node("Tome of Strahd", "ITEM"), node("Tome of Strahd", "LORE")],
            [],
            gazetteer("Tome of Strahd"),
            SLUG,
            artifacts={slugify("Tome of Strahd")},
        )

        assert nodes[0].labels == ("ITEM", "LORE")
        assert nodes[0].artifact_label == ARTIFACT_LABEL


class TestItIsNotARung:
    """The trap. A place wears exactly one rung, so writing one REMOVEs the
    others; `:Artifact` must not be caught by that, now or when the rung set
    grows."""

    def test_the_rung_set_does_not_contain_it(self):
        assert ARTIFACT_LABEL not in LOCATION_SUBTYPE_LABELS

    def test_the_rung_set_does_not_contain_item_either(self):
        """The same REMOVE would otherwise strip the type it narrows."""
        assert EntityType.ITEM.value not in LOCATION_SUBTYPE_LABELS

    def test_an_artifact_write_supersedes_nothing(self):
        """`subtype_label` names a rung to clear the others for. There is no
        artifact equivalent, because there is no sibling to clear."""
        written = plan(["Sunsword"], {"Sunsword"})

        assert written["Sunsword"].subtype_label == ""


class TestTheLabelText:
    def test_it_is_exactly_artifact(self):
        assert ARTIFACT_LABEL == "Artifact"

    def test_it_does_not_collide_with_an_entity_type(self):
        """A label that was also a type would make `MATCH (n:Artifact)` and the
        type query the same set, silently."""
        assert ARTIFACT_LABEL not in {t.value for t in EntityType}

    def test_the_seed_cannot_reach_cypher(self):
        """The seed contributes the NAME that selects a node, never the label
        text -- so a hand-edited YAML has no path into an interpolated query."""
        malicious = WriteNode(
            id="x", name="x", entity_types=("ITEM",), chapter_slug=SLUG, is_artifact=True
        )

        assert malicious.artifact_label == ARTIFACT_LABEL


class TestTheSeed:
    @pytest.fixture
    def authored(self):
        return yaml.safe_load(LOCATION_SUBTYPE_SEED.read_text())

    def test_it_lives_beside_the_location_rungs(self, authored):
        """One hand-authored file, loaded one way. Two files for two kinds of
        authored label is two mechanisms that will drift."""
        assert "artifacts" in authored
        assert "locations" in authored

    def test_it_names_the_three_tarokka_artifacts(self):
        assert load_artifacts() == {slugify(n) for n in TAROKKA}

    def test_it_is_keyed_on_the_slug(self):
        for slug in load_artifacts():
            assert slug == slugify(slug)

    def test_it_refuses_a_name_that_slugifies_to_nothing(self, tmp_path):
        """Silent otherwise: an entry that can never match anything reads in the
        graph exactly like an item nobody authored."""
        seed = tmp_path / "seed.yaml"
        seed.write_text("artifacts:\n  - '---'\n")

        with pytest.raises(ValueError, match="slugifies to nothing"):
            load_artifacts(seed)

    def test_a_seed_with_no_artifacts_block_loads_empty(self, tmp_path):
        """A book whose artifacts nobody has authored yet is a book of plain
        items, not an error."""
        seed = tmp_path / "seed.yaml"
        seed.write_text("locations: []\n")

        assert load_artifacts(seed) == frozenset()
