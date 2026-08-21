"""The read path, tested against the schema the writer actually produces.

THE FIXTURES ARE NOT INVENTED. Every graph these tests read was written by
`write_chapter` -- the real writer, the real spine, the real mention scan, the
real alias backfill -- so a test cannot pass by asserting a shape the pipeline
stopped producing. That is exactly how the previous attempt at this module came
to have a green suite while returning `section=None` against the live graph: its
fixtures set `section_heading` on entity nodes, a property the writer had
already deleted.

`TestTheSchemaTheseQueriesTarget` is the guard made explicit. It asserts the
absences -- no `entity_type`, no `section_heading`, type carried as a LABEL --
so that if the schema moves again, the failure lands here with a legible name
rather than as a lookup quietly returning nothing.

Test entities carry the `pytest:` book prefix (or a `cos:pytest-...:` chapter
scope for keyed places, whose ids `mint_id` mints) so cleanup can never reach
the real book's canon, and every token of every name is prefixed `Zz` so the
mention scan cannot match the real book's `Church` sitting in the same database.
"""

import json
from dataclasses import dataclass

import pytest

from backend.canon.aliases import WriteAlias
from backend.canon.lookup import (
    CHAPTER_NOT_EXTRACTED,
    NAME_NOT_IN_GRAPH,
    NO_SUCH_RELATIONSHIP,
    CanonLookup,
    rung_of,
    split_by_status,
    write_log_record,
)
from backend.canon.models import Section
from backend.canon.spine import plan_spine
from backend.canon.writer import (
    ACCEPTED,
    CONFLICTED,
    PROPOSED,
    WriteEdge,
    WriteNode,
    ensure_schema,
    write_chapter,
)
from backend.core.database import neo4j_session
from backend.graph.schema import RelationshipType

CHAPTER = "pytest-lookup-chapter"
BOOK = "pytest-lookup-book"
ID_PREFIX = "pytest:"
KEYED_PREFIX = f"cos:{CHAPTER}:"


# -- the pure half, which needs no database ---------------------------------


class TestTheLog:
    """The log is the deliverable, so its failure modes are tested first."""

    def test_one_json_line_per_call(self, tmp_path):
        path = tmp_path / "query-log.jsonl"
        write_log_record(path, {"tool": "where_is", "found": True})
        write_log_record(path, {"tool": "lookup", "found": False})

        lines = path.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["tool"] for line in lines] == ["where_is", "lookup"]

    def test_an_unwritable_path_does_not_raise(self, tmp_path):
        """A DM is mid-session. Losing a log line is bad; failing the lookup is
        worse."""
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")

        write_log_record(blocker / "query-log.jsonl", {"tool": "lookup"})

    def test_a_curly_apostrophe_survives_the_round_trip(self, tmp_path):
        path = tmp_path / "query-log.jsonl"
        write_log_record(path, {"args": {"place": "Bildrath’s Mercantile"}})

        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["args"]["place"] == "Bildrath’s Mercantile"


class TestTheRung:
    def test_a_rung_is_read_off_the_labels(self):
        assert rung_of(["Entity", "LOCATION", "SITE"]) == "SITE"

    def test_a_place_with_no_rung_reports_none_rather_than_a_default(self):
        """Unclassified is a real state and has to stay visible as one."""
        assert rung_of(["Entity", "LOCATION"]) is None

    def test_a_non_place_has_no_rung(self):
        assert rung_of(["Entity", "NPC"]) is None


class TestTheStatusSplit:
    def test_accepted_and_proposed_land_in_different_lists(self):
        accepted, proposed = split_by_status(
            [{"status": ACCEPTED}, {"status": PROPOSED}]
        )
        assert accepted == [{"status": ACCEPTED}]
        assert proposed == [{"status": PROPOSED}]

    def test_a_conflicted_edge_is_proposed_and_keeps_saying_so(self):
        """A demoted edge is a proposed edge that already lost, not a third
        trust level -- but a caller must still be able to see that it lost."""
        accepted, proposed = split_by_status([{"status": CONFLICTED}])
        assert accepted == []
        assert proposed == [{"status": CONFLICTED}]

    def test_a_statusless_row_is_never_accepted(self):
        """Trust is EARNED. A row that forgot to carry a status must not be
        able to arrive pre-trusted."""
        accepted, proposed = split_by_status([{"status": None}])
        assert accepted == []
        assert len(proposed) == 1


# -- the live half ----------------------------------------------------------


def _clean(session) -> None:
    session.run(
        "MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n", {"p": ID_PREFIX}
    )
    session.run(
        "MATCH (n:Entity) WHERE n.id STARTS WITH $p DETACH DELETE n", {"p": KEYED_PREFIX}
    )
    session.run("MATCH (m:Mention {chapter_slug:$c}) DETACH DELETE m", {"c": CHAPTER})
    session.run("MATCH (s:Section {chapter_slug:$c}) DETACH DELETE s", {"c": CHAPTER})
    session.run("MATCH (c:Chapter {slug:$c}) DETACH DELETE c", {"c": CHAPTER})
    session.run("MATCH (b:Book {slug:$b}) DETACH DELETE b", {"b": BOOK})
    session.run("MATCH (a:Alias) WHERE NOT (a)-[:ALIAS_OF]->() DETACH DELETE a")


def named(name: str) -> str:
    """Every token marked, so the mention scan cannot reach the real book."""
    return " ".join(f"Zz{token}" for token in name.split())


def node(
    name: str,
    entity_type: str = "NPC",
    key: str = "",
    subtype: str = "",
    artifact: bool = False,
) -> WriteNode:
    marked = named(name)
    slug = marked.lower().replace(" ", "-").replace("'", "").replace("’", "")
    node_id = f"{KEYED_PREFIX}{key.lower()}-{slug}" if key else f"{ID_PREFIX}{slug}"
    return WriteNode(
        id=node_id,
        name=marked,
        entity_types=(entity_type,),
        chapter_slug=CHAPTER,
        votes=5,
        location_subtype=subtype,
        is_artifact=artifact,
    )


def prose(index: int, heading: str, text: str) -> Section:
    return Section(
        chapter_slug=CHAPTER,
        chapter_title="A Lookup Chapter",
        heading=heading,
        index=index,
        markdown=text,
        depth=1,
        parent_index=-1,
    )


def edge(source, target, rel_type, evidence="") -> WriteEdge:
    return WriteEdge(
        source_id=source.id,
        target_id=target.id,
        rel_type=rel_type,
        chapter_slug=CHAPTER,
        evidence=evidence or "derived from document structure",
    )


#: The graph every live test reads. One settlement holding a church, the church
#: holding an undercroft, a priest placed in the undercroft by an ACCEPTED edge
#: and a vampire attached to him by a PROPOSED one -- plus an artifact and an
#: entity with no edge at all, which is the miss this exercise exists to count.
CHURCH = node("Church", "LOCATION", key="e5", subtype="SITE")
UNDERCROFT = node("Undercroft", "LOCATION", key="e5g", subtype="AREA")
VILLAGE = node("Village", "LOCATION", subtype="SETTLEMENT")
DONAVICH = node("Donavich Lightbearer", "NPC")
STRAHD = node("Strahd", "NPC")
RELIC = node("Relic", "ITEM", artifact=True)
ORPHAN = node("Orphan", "NPC")

NODES = [CHURCH, UNDERCROFT, VILLAGE, DONAVICH, STRAHD, RELIC, ORPHAN]

#: An AUTHORED short form, the shape `Ismark` has against `Ismark Kolyanovich`.
#: Written as an alias rather than inferred, which is the whole mechanism.
SHORT_FORM = "ZzDonavich"

EDGES = [
    edge(UNDERCROFT, CHURCH, RelationshipType.LOCATED_IN),
    edge(CHURCH, VILLAGE, RelationshipType.LOCATED_IN),
    edge(DONAVICH, UNDERCROFT, RelationshipType.LOCATED_IN),
    edge(STRAHD, DONAVICH, RelationshipType.THREATENS, "The devil hunts the priest."),
]

SECTIONS = [
    prose(
        0,
        f"E5. {CHURCH.name}",
        f"The {CHURCH.name} stands in the {VILLAGE.name}, and {RELIC.name} is kept here.",
    ),
    prose(
        1,
        f"E5g. {UNDERCROFT.name}",
        f"{DONAVICH.name} weeps in the {UNDERCROFT.name} below the {CHURCH.name}.",
    ),
    #: TWO sentences, and the entities are both in the SECOND. The stored
    #: evidence quoted the whole paragraph, decoy included; a derived passage is
    #: trimmed to the sentence that names the thing.
    prose(
        2,
        "Rumours",
        "Nobody speaks after dark. "
        f"{STRAHD.name} is spoken of, and so is {DONAVICH.name} again.",
    ),
    #: ONE section using BOTH of the priest's surface forms, which is the shape
    #: four sections of the real book use for `Strahd` and `Strahd von
    #: Zarovich`. It exists so a join that fans out through `USES_ALIAS` emits
    #: this passage twice and a test can catch it.
    prose(
        3,
        "Both Names",
        f"{DONAVICH.name} keeps the faith, though the villagers call {SHORT_FORM} a fool.",
    ),
]


@pytest.fixture
def graph():
    with neo4j_session() as session:
        ensure_schema(session)
        _clean(session)
        spine = plan_spine(
            book_slug=BOOK,
            book_title="A Lookup Book",
            chapter_slug=CHAPTER,
            chapter_title="A Lookup Chapter",
            chapter_index=7,
            sections=SECTIONS,
            location_ids={CHURCH.id, UNDERCROFT.id},
        )
        write_chapter(
            session,
            CHAPTER,
            NODES,
            EDGES,
            spine,
            [WriteAlias(entity_id=DONAVICH.id, name=SHORT_FORM)],
        )
        yield session
        _clean(session)


@pytest.fixture
def canon(tmp_path):
    return CanonLookup(log_path=tmp_path / "query-log.jsonl", gazetteer=None)


def log_lines(canon) -> list[dict]:
    return [json.loads(line) for line in canon.log_path.read_text(encoding="utf-8").splitlines()]


@dataclass(frozen=True)
class _Entry:
    name: str
    entity_type: str


class _StubGazetteer:
    """The book's index, standing in. Used ONLY to tell two misses apart."""

    def __init__(self, known: str) -> None:
        self.known = known

    def lookup(self, name: str):
        return _Entry(self.known, "NPC") if name == self.known else None


@pytest.mark.neo4j
class TestTheSchemaTheseQueriesTarget:
    """What the writer produces, asserted so a schema move fails loudly here."""

    def test_the_type_is_a_label_and_not_a_property(self, graph):
        row = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS labels, keys(n) AS keys",
            {"id": DONAVICH.id},
        ).single()
        assert "NPC" in row["labels"]
        assert "entity_type" not in row["keys"]

    def test_an_entity_carries_no_section_heading(self, graph):
        """The property the previous attempt read. Its absence is the reason
        that suite passed while the tool returned nothing."""
        keys = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN keys(n) AS keys", {"id": CHURCH.id}
        ).single()["keys"]
        assert "section_heading" not in keys
        assert "chapter_slug" not in keys

    def test_a_section_carries_the_heading_and_a_key(self, graph):
        row = graph.run(
            """
            MATCH (c:Chapter {slug:$c})-[:HAS_SECTION]->(s:Section {index:0})
            RETURN s.heading AS heading, s.key AS key, s.index AS index
            """,
            {"c": CHAPTER},
        ).single()
        assert row["heading"] == f"E5. {CHURCH.name}"
        assert row["key"] == "e5"
        assert row["index"] == 0

    def test_a_rung_is_a_label(self, graph):
        labels = graph.run(
            "MATCH (n:Entity {id:$id}) RETURN labels(n) AS l", {"id": UNDERCROFT.id}
        ).single()["l"]
        assert "AREA" in labels and "LOCATION" in labels

    def test_a_mention_stores_an_offset_and_no_prose(self, graph):
        """The deletion, asserted where it matters -- on the node itself. The
        section keeps the ONE copy of the text; the mention keeps the offset
        into it."""
        row = graph.run(
            """
            MATCH (:Entity {id:$id})<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(s:Section)
            RETURN properties(m) AS props, s.text AS text, s.heading AS heading LIMIT 1
            """,
            {"id": DONAVICH.id},
        ).single()
        assert "evidence" not in row["props"]
        assert row["props"]["offsets"][0] >= 0
        assert DONAVICH.name in row["text"]
        assert row["heading"]

    def test_no_mention_in_the_graph_carries_evidence(self, graph):
        """Over the whole chapter rather than one node: a MERGE that kept the
        old property on a re-write would leave it on some mentions and not
        others, and a LIMIT 1 check would pass on whichever it saw."""
        left = graph.run(
            "MATCH (m:Mention {chapter_slug:$c}) WHERE m.evidence IS NOT NULL "
            "RETURN count(m) AS c",
            {"c": CHAPTER},
        ).single()["c"]
        total = graph.run(
            "MATCH (m:Mention {chapter_slug:$c}) RETURN count(m) AS c", {"c": CHAPTER}
        ).single()["c"]
        assert total > 0
        assert left == 0


@pytest.mark.neo4j
class TestWhereIs:
    def test_it_returns_the_accepted_placement(self, graph, canon):
        result = canon.where_is(DONAVICH.name)

        assert result["found"] is True
        assert [(p["relationship"], p["place"]) for p in result["accepted"]] == [
            ("LOCATED_IN", UNDERCROFT.name)
        ]

    def test_the_place_carries_its_rung(self, graph, canon):
        placement = canon.where_is(DONAVICH.name)["accepted"][0]
        assert placement["place_rung"] == "AREA"

    def test_it_reports_the_chapter_and_section_where_it_is_discussed(self, graph, canon):
        passages = canon.where_is(DONAVICH.name)["passages"]

        assert {p["section"] for p in passages} == {
            f"E5g. {UNDERCROFT.name}",
            "Rumours",
            "Both Names",
        }
        assert {p["chapter"] for p in passages} == {CHAPTER}
        assert {p["chapter_index"] for p in passages} == {7}

    def test_a_passage_is_listed_once_however_many_spellings_it_used(self, graph, canon):
        """`Both Names` uses two surface forms of the priest. A join through
        `USES_ALIAS` emits it twice; a DM must see the passage once."""
        passages = canon.where_is(DONAVICH.name)["passages"]

        seen = [(p["chapter"], p["section"]) for p in passages]
        assert len(seen) == len(set(seen)), seen

    def test_a_containing_place_is_read_from_the_other_end_too(self, graph, canon):
        """`CONTAINS` points place -> entity, so a placement written that way is
        still a placement."""
        with neo4j_session() as session:
            session.run(
                """
                MATCH (p:Entity {id:$p}), (o:Entity {id:$o})
                MERGE (p)-[r:CONTAINS]->(o) SET r.status = $status
                """,
                {"p": CHURCH.id, "o": ORPHAN.id, "status": ACCEPTED},
            )
        result = canon.where_is(ORPHAN.name)
        assert [(p["relationship"], p["place"]) for p in result["accepted"]] == [
            ("CONTAINS", CHURCH.name)
        ]

    def test_a_node_with_no_placement_is_a_no_such_relationship_miss(self, graph, canon):
        result = canon.where_is(ORPHAN.name)

        assert result["found"] is False
        assert result["miss_reason"] == NO_SUCH_RELATIONSHIP
        assert result["entities"][0]["name"] == ORPHAN.name

    def test_a_name_the_graph_does_not_hold_is_a_name_not_in_graph_miss(self, graph, canon):
        result = canon.where_is("ZzRictavio")

        assert result["found"] is False
        assert result["miss_reason"] == NAME_NOT_IN_GRAPH
        assert result["entities"] == []


@pytest.mark.neo4j
class TestWhatsHere:
    def test_it_returns_what_is_inside(self, graph, canon):
        result = canon.whats_here(CHURCH.name)

        assert result["found"] is True
        assert {row["name"] for row in result["accepted"]} == {UNDERCROFT.name}

    def test_an_occupant_carries_its_labels_and_rung(self, graph, canon):
        occupant = canon.whats_here(CHURCH.name)["accepted"][0]
        assert occupant["rung"] == "AREA"
        assert "LOCATION" in occupant["labels"]

    def test_it_reports_what_else_the_section_says(self, graph, canon):
        sections = canon.whats_here(CHURCH.name)["sections"]

        described = [s for s in sections if s["section"] == f"E5. {CHURCH.name}"]
        assert described, sections
        assert VILLAGE.name in described[0]["also_mentions"]
        assert RELIC.name in described[0]["also_mentions"]
        assert CHURCH.name not in described[0]["also_mentions"]

    def test_a_place_with_nothing_in_it_is_a_no_such_relationship_miss(self, graph, canon):
        result = canon.whats_here(UNDERCROFT.name)
        # The undercroft holds a person, so pick the one that truly holds nothing.
        assert result["found"] is True

        empty = canon.whats_here(RELIC.name)
        assert empty["found"] is False
        assert empty["miss_reason"] == NO_SUCH_RELATIONSHIP

    def test_a_person_placed_in_a_room_is_found_from_the_room(self, graph, canon):
        result = canon.whats_here(UNDERCROFT.name)
        assert {row["name"] for row in result["accepted"]} == {DONAVICH.name}

    def test_a_section_is_listed_once_and_names_a_thing_once(self, graph, canon):
        """The same fan-out asked of the other join. `E5g.` mentions the priest,
        who answers to two spellings; neither the section nor his name may
        repeat."""
        sections = canon.whats_here(UNDERCROFT.name)["sections"]

        seen = [(s["chapter"], s["section"]) for s in sections]
        assert len(seen) == len(set(seen)), seen
        for section in sections:
            assert len(section["also_mentions"]) == len(set(section["also_mentions"]))
        assert DONAVICH.name in sections[0]["also_mentions"]

    def test_an_occupant_is_listed_once_per_relationship(self, graph, canon):
        rows = canon.whats_here(CHURCH.name)["accepted"] + canon.whats_here(CHURCH.name)[
            "proposed"
        ]
        seen = [(row["id"], row["relationship"]) for row in rows]
        assert len(seen) == len(set(seen)), seen


@pytest.mark.neo4j
class TestLookup:
    def test_it_returns_the_labels(self, graph, canon):
        entity = canon.lookup(CHURCH.name)["entities"][0]
        assert set(entity["labels"]) == {"LOCATION", "SITE"}

    def test_it_returns_the_rung_when_there_is_one(self, graph, canon):
        assert canon.lookup(VILLAGE.name)["entities"][0]["rung"] == "SETTLEMENT"

    def test_an_artifact_is_visible_as_one(self, graph, canon):
        entity = canon.lookup(RELIC.name)["entities"][0]
        assert entity["artifact"] is True
        assert entity["rung"] is None

    def test_it_returns_the_mentions_with_their_evidence(self, graph, canon):
        """Nothing stores this any more, and every mention still has one."""
        mentions = canon.lookup(DONAVICH.name)["mentions"]

        assert mentions
        assert all(DONAVICH.name in m["evidence"] for m in mentions)
        assert {m["section"] for m in mentions} == {
            f"E5g. {UNDERCROFT.name}",
            "Rumours",
            "Both Names",
        }

    def test_the_evidence_is_the_sentence_and_not_the_paragraph(self, graph, canon):
        """THE POINT OF THE CHANGE. `Rumours` opens with a sentence naming
        nobody; the stored evidence quoted it along with everything else."""
        rumours = [
            m for m in canon.lookup(DONAVICH.name)["mentions"] if m["section"] == "Rumours"
        ]
        assert len(rumours) == 1
        assert rumours[0]["evidence"] == (
            f"{STRAHD.name} is spoken of, and so is {DONAVICH.name} again."
        )
        assert "Nobody speaks after dark" not in rumours[0]["evidence"]

    def test_the_section_text_is_not_handed_back_with_the_mention(self, graph, canon):
        """The whole section travels to derive the passage and stops there.
        Returning it would put the duplication back on the wire and into every
        caller's context, which is the cost this change exists to remove."""
        mentions = canon.lookup(DONAVICH.name)["mentions"]
        assert mentions
        for mention in mentions:
            assert "section_text" not in mention
            assert "text" not in mention

    def test_every_mention_gets_a_passage_even_where_the_offset_is_zero(self, graph, canon):
        """A falsy offset is a real offset. A truthiness check on it would drop
        the passage for every entity a section opens with."""
        mentions = canon.lookup(STRAHD.name)["mentions"]
        assert mentions
        assert all(m["evidence"].strip() for m in mentions)

    def test_a_mention_records_which_spellings_the_book_used(self, graph, canon):
        mentions = canon.lookup(DONAVICH.name)["mentions"]
        assert all(DONAVICH.name in m["aliases"] for m in mentions)

    def test_one_row_per_mention_however_many_spellings_it_used(self, graph, canon):
        """THE FAN-OUT. `Both Names` writes the priest's full name and his short
        form, so that one mention carries two `USES_ALIAS` edges. A naive join
        emits the passage twice, and every count taken off the list inflates --
        by 29% for `Strahd` in the real book, whose two names collide in four
        sections. One row per mention, always."""
        mentions = canon.lookup(DONAVICH.name)["mentions"]

        seen = [(m["chapter"], m["section"]) for m in mentions]
        assert len(seen) == len(set(seen)), seen

    def test_the_surface_forms_are_kept_rather_than_dropped(self, graph, canon):
        """Deduplicating must not cost the information. WHICH name the book used
        at a given point is story information -- the party meets `Strahd` well
        before `Strahd von Zarovich` -- so the row carries a LIST."""
        both = [
            m for m in canon.lookup(DONAVICH.name)["mentions"] if m["section"] == "Both Names"
        ]
        assert len(both) == 1
        assert both[0]["aliases"] == sorted([DONAVICH.name, SHORT_FORM])

    def test_the_spellings_are_ordered_so_two_runs_agree(self, graph, canon):
        aliases = [m["aliases"] for m in canon.lookup(DONAVICH.name)["mentions"]]
        assert all(names == sorted(names) for names in aliases)

    def test_an_entity_with_one_spelling_still_carries_it_in_a_list(self, graph, canon):
        """The shape must not change with the number of aliases."""
        mentions = canon.lookup(STRAHD.name)["mentions"]
        assert mentions
        assert all(m["aliases"] == [STRAHD.name] for m in mentions)

    def test_edges_in_both_directions_are_returned(self, graph, canon):
        result = canon.lookup(DONAVICH.name)
        directions = {(row["direction"], row["relationship"]) for row in result["accepted"]}
        directions |= {(row["direction"], row["relationship"]) for row in result["proposed"]}

        assert ("out", "LOCATED_IN") in directions
        assert ("in", "THREATENS") in directions

    def test_accepted_and_proposed_are_never_merged(self, graph, canon):
        result = canon.lookup(DONAVICH.name)

        assert {row["relationship"] for row in result["accepted"]} == {"LOCATED_IN"}
        assert {row["relationship"] for row in result["proposed"]} == {"THREATENS"}
        assert all(row["status"] == ACCEPTED for row in result["accepted"])
        assert all(row["status"] != ACCEPTED for row in result["proposed"])

    def test_an_edge_is_listed_once(self, graph, canon):
        """Neither edge query touches `:Alias`, so this is a guard rather than a
        fix -- but it is the same property, and it is cheap to keep true."""
        result = canon.lookup(DONAVICH.name)
        rows = result["accepted"] + result["proposed"]

        seen = [(r["direction"], r["relationship"], r["other_id"]) for r in rows]
        assert len(seen) == len(set(seen)), seen

    def test_the_entity_itself_is_listed_once(self, graph, canon):
        entities = canon.lookup(DONAVICH.name)["entities"]
        assert len(entities) == len({e["id"] for e in entities})

    def test_a_node_with_no_edge_is_still_found(self, graph, canon):
        """"Tell me about X" is answered by the node existing."""
        result = canon.lookup(ORPHAN.name)
        assert result["found"] is True
        assert result["accepted"] == [] and result["proposed"] == []


@pytest.mark.neo4j
class TestNameResolution:
    """One path -- `resolve_name` -- and nothing fuzzy behind it."""

    def test_the_canonical_name_resolves(self, graph, canon):
        assert canon.lookup(DONAVICH.name)["found"] is True

    def test_an_authored_short_form_resolves_to_the_same_entity(self, graph, canon):
        """`Ismark` and `Ismark Kolyanovich`, in miniature."""
        short = canon.lookup(SHORT_FORM)
        full = canon.lookup(DONAVICH.name)

        assert short["found"] is True
        assert [e["id"] for e in short["entities"]] == [e["id"] for e in full["entities"]]

    def test_case_is_folded(self, graph, canon):
        assert canon.lookup(DONAVICH.name.upper())["found"] is True

    def test_the_apostrophe_a_dm_types_resolves(self, graph, canon):
        """The book sets U+2019 and a DM types `'`. One entity, either way."""
        with neo4j_session() as session:
            session.run(
                """
                MATCH (e:Entity {id:$id})
                MERGE (a:Alias {name:$name}) SET a.normalized = $normalized
                MERGE (a)-[:ALIAS_OF]->(e)
                """,
                {
                    "id": CHURCH.id,
                    "name": "ZzDonavich’s ZzChurch",
                    "normalized": "zzdonavich's zzchurch",
                },
            )
        assert canon.lookup("ZzDonavich's ZzChurch")["found"] is True

    def test_a_near_miss_spelling_resolves_to_nothing(self, graph, canon):
        """`Ismar` must reach `Ismark` never. No edit distance, no prefix."""
        assert canon.lookup(SHORT_FORM[:-1])["found"] is False
        assert canon.lookup(SHORT_FORM[:-1])["miss_reason"] == NAME_NOT_IN_GRAPH

    def test_a_prefix_of_a_real_name_resolves_to_nothing(self, graph, canon):
        assert canon.where_is("ZzDonav")["found"] is False

    def test_a_token_of_a_real_name_does_not_credit_the_whole(self, graph, canon):
        """The token-subset rule that once let `Ireena` credit a whole quest."""
        assert canon.lookup("ZzLightbearer")["found"] is False


@pytest.mark.neo4j
class TestTheQueryLog:
    def test_every_call_writes_one_line(self, graph, canon):
        canon.where_is(DONAVICH.name)
        canon.whats_here(CHURCH.name)
        canon.lookup(RELIC.name)

        assert [line["tool"] for line in log_lines(canon)] == [
            "where_is",
            "whats_here",
            "lookup",
        ]

    def test_a_hit_records_the_arguments_and_the_counts(self, graph, canon):
        canon.lookup(DONAVICH.name)
        line = log_lines(canon)[0]

        assert line["args"] == {"name": DONAVICH.name}
        assert line["found"] is True
        assert line["accepted"] == 1
        assert line["proposed"] == 1
        assert "miss_reason" not in line

    def test_a_miss_records_why_it_was_empty(self, graph, canon):
        canon.where_is(ORPHAN.name)
        line = log_lines(canon)[0]

        assert line["found"] is False
        assert line["miss_reason"] == NO_SUCH_RELATIONSHIP
        assert ORPHAN.name in line["miss_detail"]

    def test_a_miss_records_which_chapters_the_graph_holds(self, graph, canon):
        canon.where_is("ZzNobody")
        line = log_lines(canon)[0]

        assert CHAPTER in line["chapters_in_graph"]

    def test_a_name_the_book_knows_and_the_graph_does_not_says_so(self, graph, tmp_path):
        canon = CanonLookup(
            log_path=tmp_path / "query-log.jsonl", gazetteer=_StubGazetteer("ZzVasilka")
        )
        result = canon.lookup("ZzVasilka")

        assert result["miss_reason"] == CHAPTER_NOT_EXTRACTED
        assert log_lines(canon)[0]["miss_reason"] == CHAPTER_NOT_EXTRACTED

    def test_a_node_present_without_the_edge_outranks_what_the_book_knows(
        self, graph, tmp_path
    ):
        """The miss worth acting on: both ends exist and only the edge is
        missing. Nothing the gazetteer says may mask it."""
        canon = CanonLookup(
            log_path=tmp_path / "query-log.jsonl", gazetteer=_StubGazetteer(ORPHAN.name)
        )
        assert canon.where_is(ORPHAN.name)["miss_reason"] == NO_SUCH_RELATIONSHIP


@pytest.mark.neo4j
class TestTheProposedLayerIsNeverLaundered:
    """The reason the split exists, asserted end to end.

    `Ismark OPPOSES Ireena` is in the real graph and he is her brother. A caller
    that received one flat list would hand that to a table as fact.
    """

    def test_a_proposed_placement_never_appears_among_the_accepted(self, graph, canon):
        with neo4j_session() as session:
            session.run(
                """
                MATCH (o:Entity {id:$o}), (p:Entity {id:$p})
                MERGE (o)-[r:LOCATED_IN]->(p) SET r.status = $status
                """,
                {"o": ORPHAN.id, "p": CHURCH.id, "status": PROPOSED},
            )
        result = canon.where_is(ORPHAN.name)

        assert result["accepted"] == []
        assert [row["place"] for row in result["proposed"]] == [CHURCH.name]
        assert result["found"] is True

    def test_a_proposed_occupant_never_appears_among_the_accepted(self, graph, canon):
        with neo4j_session() as session:
            session.run(
                """
                MATCH (p:Entity {id:$p}), (o:Entity {id:$o})
                MERGE (p)-[r:CONTAINS]->(o) SET r.status = $status
                """,
                {"p": VILLAGE.id, "o": STRAHD.id, "status": PROPOSED},
            )
        result = canon.whats_here(VILLAGE.name)

        assert STRAHD.name not in {row["name"] for row in result["accepted"]}
        assert STRAHD.name in {row["name"] for row in result["proposed"]}


@pytest.mark.neo4j
class TestTheRealBook:
    """Two assertions against the book's own canon, not against a fixture.

    Narrow on purpose. A concurrent fix to the mention scan moves counts under
    this file, so nothing here depends on one.
    """

    def test_ismark_and_ismark_kolyanovich_are_the_same_entity(self, canon):
        short = canon.lookup("Ismark")
        full = canon.lookup("Ismark Kolyanovich")

        assert short["found"] is True
        assert [e["id"] for e in short["entities"]] == [e["id"] for e in full["entities"]]

    def test_ismar_resolves_to_nothing(self, canon):
        result = canon.lookup("Ismar")
        assert result["found"] is False
        assert result["miss_reason"] == NAME_NOT_IN_GRAPH

    def test_strahds_two_names_do_not_inflate_his_mentions(self, canon):
        """Against the book's own canon, and COUNT-FREE on purpose.

        Four sections write both `Strahd` and `Strahd von Zarovich`, which made
        the naive join return 18 rows for 14 mentions. The assertion compares
        two quantities derived from the same answer rather than naming either,
        so the concurrent mention-scan fix can move both without touching it.
        """
        mentions = canon.lookup("Strahd")["mentions"]

        assert mentions
        # Keyed on `mention_id`, which IS the identity, rather than on
        # `(chapter, heading)`. *Corrected 2026-08-17*, when the whole book
        # landed: a heading does not identify a section and this file's own
        # neighbours say so -- Death House has two `Storage Room`s and two
        # `Spare Bedroom`s, chapter 4 four `Treasure`s. The test failed on 261
        # rows against 260 distinct headings, which was the BOOK being right and
        # the key being wrong.
        seen = [m["mention_id"] for m in mentions]
        assert len(seen) == len(set(seen)), sorted(seen)

    def test_a_section_using_both_of_strahds_names_keeps_both(self, canon):
        """Deduplicating must not have cost the surface forms."""
        mentions = canon.lookup("Strahd")["mentions"]

        multi = [m for m in mentions if len(m["aliases"]) > 1]
        assert multi, "no section of the real book uses two of Strahd's names"
        assert {"Strahd", "Strahd von Zarovich"} <= set(multi[0]["aliases"])


def test_the_default_log_path_is_under_data():
    """Gitignored, and where the previous run's log already lives."""
    assert CanonLookup().log_path.as_posix().endswith("data/query-log.jsonl")
