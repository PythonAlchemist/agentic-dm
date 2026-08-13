"""The top of the spatial hierarchy, and the rungs below it.

Two things that turned out to be one thing. `derive_structure` emits `The
Village of Barovia CONTAINS Church` for every top-level keyed area a chapter
holds, naming the parent after the CHAPTER TITLE -- and no candidate the
extractor produced is called that, so every one of those edges was dropped as
dangling and the hierarchy was severed at the top: rooms nested under `Church`
correctly while `Church` itself hung from nothing.

The subtypes need the same fact. `SITE` is a top-level key *or a chapter's own
place*, so the chapter place has to exist as a node before it can be labelled
one.

Pure: `plan_write` never opens a connection, so both halves are assertable
without a database. The label that actually lands is pinned in
`test_write_canon_neo4j.py`.
"""

import pytest

from backend.canon.assembler import slugify
from backend.canon.gazetteer import Gazetteer, GazetteerEntry
from backend.canon.models import CandidateEdge, CandidateNode
from backend.canon.structure import STRUCTURAL_EVIDENCE
from backend.canon.writer import WriteNode, mint_id, plan_write
from backend.graph.schema import EntityType, LocationSubtype

SLUG = "the-village-of-barovia"
VILLAGE = "The Village of Barovia"

DERIVED = {"evidence": STRUCTURAL_EVIDENCE, "layer": "spatial"}


def gazetteer(*names: str) -> Gazetteer:
    return Gazetteer([GazetteerEntry(name=n, entity_type="NPC", wiki_category="c") for n in names])


def node(name: str, entity_type: str = "LOCATION", **kwargs) -> CandidateNode:
    return CandidateNode(name=name, entity_type=entity_type, chapter_slug=SLUG, **kwargs)


def edge(source: str, target: str, rel_type: str = "CONTAINS", **kwargs) -> CandidateEdge:
    return CandidateEdge(
        source_name=source, target_name=target, rel_type=rel_type, chapter_slug=SLUG, **kwargs
    )


class TestChapterPlace:
    """The chapter's own place has to be a node before its edges can land."""

    def plan(self, chapter_place: str | None = VILLAGE):
        return plan_write(
            [
                node("Church", section_heading="E5. Church", section_index=1),
                node("Undercroft", section_heading="E5g. Undercroft", section_index=2),
            ],
            [
                edge(VILLAGE, "Church", **DERIVED),
                edge("Church", "Undercroft", **DERIVED),
            ],
            gazetteer(),
            SLUG,
            chapter_place=chapter_place,
        )

    def test_the_chapter_place_becomes_a_node(self):
        nodes, _, _ = self.plan()

        assert VILLAGE in [n.name for n in nodes]

    def test_its_id_is_global_to_the_book(self):
        """A village is one village whichever chapter is about it."""
        nodes, _, _ = self.plan()

        village = next(n for n in nodes if n.name == VILLAGE)
        assert village.id == mint_id(SLUG, VILLAGE) == "cos:the-village-of-barovia"

    def test_it_is_a_location(self):
        nodes, _, _ = self.plan()

        village = next(n for n in nodes if n.name == VILLAGE)
        assert village.entity_types == (EntityType.LOCATION.value,)

    def test_it_is_accepted(self):
        """A chapter's own heading is the book's assertion, not a model's."""
        nodes, _, _ = self.plan()

        village = next(n for n in nodes if n.name == VILLAGE)
        assert village.status == "accepted"

    def test_the_chapter_derived_containment_lands(self):
        """The regression, stated as a test: this edge used to dangle."""
        _, edges, report = self.plan()

        assert report.dangling_edges == 0
        assert ("cos:the-village-of-barovia", mint_id(SLUG, "Church", "e5")) in [
            (e.source_id, e.target_id) for e in edges
        ]

    def test_without_a_chapter_place_the_edge_still_dangles(self):
        """The old behaviour kept honest: nothing here invents a parent."""
        _, edges, report = self.plan(chapter_place=None)

        assert report.dangling_edges == 1
        assert len(edges) == 1

    def test_a_chapter_that_keys_nothing_gets_no_place_node(self):
        """A title is not evidence of a place: chapter 1 keys Tarokka cards."""
        nodes, _, _ = plan_write(
            [node("Madam Eva", "NPC")],
            [],
            gazetteer("Madam Eva"),
            SLUG,
            chapter_place="Into the Mists",
        )

        assert [n.name for n in nodes] == ["Madam Eva"]

    def test_a_candidate_of_the_same_name_is_not_duplicated(self):
        """The extractor naming the village too must not mint a second one."""
        nodes, _, _ = plan_write(
            [
                node("Church", section_heading="E5. Church", section_index=1),
                node(VILLAGE, section_index=1),
            ],
            [edge(VILLAGE, "Church", **DERIVED)],
            gazetteer(VILLAGE),
            SLUG,
            chapter_place=VILLAGE,
        )

        assert [n.name for n in nodes].count(VILLAGE) == 1

    def test_it_survives_the_gazetteer(self):
        """A chapter title is the book's own heading, like a keyed area -- and
        the wiki indexes 38 places against the book's 414 keyed areas."""
        nodes, _, report = self.plan()

        assert report.gazetteer_dropped == 0
        assert VILLAGE in [n.name for n in nodes]

    def test_it_is_counted_as_a_written_node(self):
        """Every node that lands is in the total, or the accounting lies."""
        nodes, _, report = self.plan()

        assert report.written_nodes == len(nodes) == 3

    def test_it_is_counted_apart_from_the_candidates(self):
        """The verifier's identity is `written + every named drop ==
        candidates`, and this node came from outside the candidate set. It gets
        its own term rather than being folded into one of the others, where it
        would silently offset a real drop."""
        _, _, report = self.plan()

        assert report.derived_nodes == 1
        assert report.candidate_nodes == 2
        assert report.written_nodes + report.gazetteer_dropped + report.duplicate_nodes == (
            report.candidate_nodes + report.derived_nodes
        )

    def test_a_candidate_of_the_same_name_is_not_counted_as_derived(self):
        """Nothing was minted -- the candidate already carried that id -- and
        counting it would inflate the right-hand side of the identity."""
        _, _, report = plan_write(
            [
                node("Church", section_heading="E5. Church", section_index=1),
                node(VILLAGE, section_index=1),
            ],
            [edge(VILLAGE, "Church", **DERIVED)],
            gazetteer(VILLAGE),
            SLUG,
            chapter_place=VILLAGE,
        )

        assert report.derived_nodes == 0

    def test_a_chapter_with_no_place_derives_nothing(self):
        _, _, report = self.plan(chapter_place=None)

        assert report.derived_nodes == 0


class TestDerivedSubtypes:
    """`SITE` and `AREA` are read off the key convention, never guessed."""

    def plan(self, *nodes_, **kwargs):
        return plan_write(
            list(nodes_), [], gazetteer(*[n.name for n in nodes_]), SLUG, **kwargs
        )

    def test_a_suffixed_key_is_an_area(self):
        nodes, _, _ = self.plan(node("Chapel", section_heading="E5f. Chapel", section_index=1))

        assert nodes[0].location_subtype == LocationSubtype.AREA.value

    def test_an_unsuffixed_key_is_a_site(self):
        nodes, _, _ = self.plan(node("Church", section_heading="E5. Church", section_index=1))

        assert nodes[0].location_subtype == LocationSubtype.SITE.value

    def test_a_two_digit_stem_still_parses(self):
        """`K18a` is a room inside `K18`; `K42` is a building."""
        nodes, _, _ = self.plan(
            node("High Tower Shaft", section_heading="K18a. High Tower Shaft", section_index=1),
            node("Study", section_heading="K42. Study", section_index=2),
        )

        assert [n.location_subtype for n in nodes] == [
            LocationSubtype.AREA.value,
            LocationSubtype.SITE.value,
        ]

    def test_a_room_mentioned_from_elsewhere_keeps_its_own_rung(self):
        """`Undercroft` named from inside `E5a. Hall` is still the room at E5g,
        which is what `key_for` resolves -- and a room, not a building."""
        nodes, _, _ = self.plan(
            node("Undercroft", section_heading="E5g. Undercroft", section_index=2),
            node("Undercroft", section_heading="E5a. Hall", section_index=1),
        )

        assert [n.location_subtype for n in nodes] == [LocationSubtype.AREA.value]

    def test_the_chapters_own_place_is_a_site(self):
        nodes, _, _ = plan_write(
            [node("Chapel", section_heading="K7. Chapel", section_index=1)],
            [],
            gazetteer(),
            SLUG,
            chapter_place="Castle Ravenloft",
        )

        castle = next(n for n in nodes if n.name == "Castle Ravenloft")
        assert castle.location_subtype == LocationSubtype.SITE.value

    def test_an_unkeyed_place_stays_plain(self):
        """No default. An unclassified place must be visibly unclassified."""
        nodes, _, _ = self.plan(node("Castle Ravenloft"))

        assert nodes[0].location_subtype == ""
        assert nodes[0].subtype_label == ""

    def test_a_keyed_non_location_gets_no_subtype(self):
        """`E5d. Trapdoor` was typed ITEM by the extractor, and an item is not
        a rung of the LOCATION hierarchy."""
        nodes, _, _ = self.plan(
            node("Trapdoor", "ITEM", section_heading="E5d. Trapdoor", section_index=1)
        )

        assert nodes[0].location_subtype == ""

    def test_a_disputed_type_that_includes_location_still_gets_one(self):
        """`Barovia` is `:LOCATION:SETTING`. One of its labels is on the
        hierarchy, and refusing the rung because the other is not would drop a
        fact the LOCATION label supports."""
        nodes, _, _ = self.plan(
            node("Barovia", "LOCATION", section_heading="E9. Barovia", section_index=1),
            node("Barovia", "SETTING", section_heading="E9. Barovia", section_index=1),
        )

        assert nodes[0].entity_types == ("LOCATION", "SETTING")
        assert nodes[0].location_subtype == LocationSubtype.SITE.value


class TestHandAuthoredSubtypes:
    """REGION, SETTLEMENT and WILD are authored, not inferred.

    Roughly fifteen entries for the whole book. Nothing infers them from a name
    substring like "Village of": that works on Barovia and breaks on the next
    book.
    """

    def plan(self, *nodes_, subtypes=None, **kwargs):
        return plan_write(
            list(nodes_),
            [],
            gazetteer(*[n.name for n in nodes_]),
            SLUG,
            subtypes=subtypes,
            **kwargs,
        )

    def test_an_authored_entry_decides(self):
        nodes, _, _ = self.plan(
            node("Svalich Woods"), subtypes={"svalich-woods": LocationSubtype.WILD}
        )

        assert nodes[0].location_subtype == LocationSubtype.WILD.value

    def test_it_is_matched_on_the_slug_not_the_spelling(self):
        """`Mad Mary's` and `Mad Mary’s` differ by one invisible character --
        the DDB corpus keeps the book's U+2019 and the extractor sometimes emits
        an ASCII quote. Anything `slugify` treats as one name is one name."""
        authored = {slugify("Mad Mary's Townhouse"): LocationSubtype.SETTLEMENT}

        nodes, _, _ = self.plan(node("Mad Mary’s Townhouse"), subtypes=authored)

        assert nodes[0].location_subtype == LocationSubtype.SETTLEMENT.value

    def test_an_authored_entry_beats_the_key(self):
        """The village is a chapter's own place, which derives SITE -- and a
        human has said it is a settlement. A key does not overrule a human."""
        nodes, _, _ = plan_write(
            [node("Church", section_heading="E5. Church", section_index=1)],
            [],
            gazetteer(),
            SLUG,
            chapter_place=VILLAGE,
            subtypes={"the-village-of-barovia": LocationSubtype.SETTLEMENT},
        )

        village = next(n for n in nodes if n.name == VILLAGE)
        assert village.location_subtype == LocationSubtype.SETTLEMENT.value

    def test_an_authored_entry_for_a_non_location_confers_nothing(self):
        nodes, _, _ = self.plan(
            node("Madam Eva", "NPC"), subtypes={"madam-eva": LocationSubtype.WILD}
        )

        assert nodes[0].location_subtype == ""


class TestSubtypeLabel:
    """What reaches the interpolated Cypher, and what cannot."""

    def test_the_subtype_is_a_label_beside_location(self):
        node_ = WriteNode(
            id="x",
            name="Chapel",
            entity_types=("LOCATION",),
            chapter_slug=SLUG,
            location_subtype=LocationSubtype.AREA.value,
        )

        assert node_.labels == ("LOCATION",)
        assert node_.subtype_label == "AREA"

    def test_a_subtype_outside_the_hierarchy_confers_no_label(self):
        """A label cannot be parameterized in Cypher, so only the enum's own
        names may reach the statement text."""
        node_ = WriteNode(
            id="x",
            name="x",
            entity_types=("LOCATION",),
            chapter_slug=SLUG,
            location_subtype="DROP DATABASE neo4j",
        )

        assert node_.subtype_label == ""

    @pytest.mark.parametrize("subtype", list(LocationSubtype))
    def test_every_declared_subtype_is_admitted(self, subtype):
        """A rung the enum declares but the writer refuses would be invisible
        with no error, which is how a filter hides a defect for weeks."""
        node_ = WriteNode(
            id="x",
            name="x",
            entity_types=("LOCATION",),
            chapter_slug=SLUG,
            location_subtype=subtype.value,
        )

        assert node_.subtype_label == subtype.value

    def test_no_subtype_shares_a_name_with_an_entity_type(self):
        """Both are labels on the same node. A collision would make
        `MATCH (n:SETTING)` answer for two unrelated questions."""
        assert not {s.value for s in LocationSubtype} & {t.value for t in EntityType}
