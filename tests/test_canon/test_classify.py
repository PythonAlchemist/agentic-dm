"""Stage B: re-decide an extracted pair's relationship in a focused call.

Four properties carry the experiment, and each has a class here. Weakening any
one of them does not break the code -- it silently changes what the measured
numbers mean, which is why they are tested rather than merely commented.

- `TestNoAnchoring` -- the classifier must not see the original `rel_type` or
  the original direction. Note the naive assertion ("the prompt does not contain
  the string KNOWS") is UNSATISFIABLE and would be a test that passes for the
  wrong reason: KNOWS is frequently a legal option and appears for that reason.
  The real property is that two edges differing ONLY in `rel_type` render the
  identical prompt, and that an edge and its reverse render the identical
  prompt.
- `TestOfferedVocabulary` -- only type-legal relations are offered, in the legal
  direction only.
- `TestNoLegalRelation` -- a pair the table admits nothing for is declined
  without spending a call.
- `TestParsing` -- a batch that answers 7 of 10 items must not shift the other
  three onto the wrong pairs, and a silence must never be recorded as a decline.
  Those two are the failure modes that would corrupt the measurement while
  looking like a result.

Two more classes cover the corrections a hand read of the first run's output
forced:

- `TestSelfPairsAreRejectedBeforeTheModelSeesThem` -- `Helga Ruvak -IDENTITY_OF->
  Helga Ruvak` survived that run and shipped in its fabrication sample.
- `TestSeveralRelationsPerPair` -- one of the three golden edges that run lost
  was a sentence stating TWO true relations where the design allowed one. The
  cap is the risk here, so `capped` is tested as carefully as the feature.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.canon.classify import (
    NO_ANSWER,
    NONE_RELATION,
    Decision,
    Pair,
    RelationClassifier,
    is_self_pair,
    legal_relations,
    offered_options,
    pairs_from_edges,
    parse_types,
    render_option,
    render_prompt,
    render_types,
)
from backend.canon.extract import EXTRACTION_SEED
from backend.canon.models import CandidateEdge, CandidateNode
from backend.graph.schema import (
    CANON_ENTITY_TYPES,
    RELATIONSHIP_DOMAIN_RANGE,
    RELATIONSHIP_GLOSS,
    EntityType,
    RelationshipType,
)


def pair(
    a_name: str = "Ismark",
    a_type: str = "NPC",
    b_name: str = "Vallaki",
    b_type: str = "LOCATION",
    evidence: str = "He wants to escort Ireena to Vallaki.",
    section_heading: str = "E2. Blood of the Vine Tavern",
) -> Pair:
    return Pair(
        a_name=a_name,
        a_type=a_type,
        b_name=b_name,
        b_type=b_type,
        evidence=evidence,
        section_heading=section_heading,
        chapter_slug="chapter-3-the-village-of-barovia",
        section_index=3,
    )


def edge(source: str, rel_type: str, target: str, **kwargs) -> CandidateEdge:
    return CandidateEdge(source_name=source, rel_type=rel_type, target_name=target, **kwargs)


def node(name: str, entity_type: str) -> CandidateNode:
    return CandidateNode(name=name, entity_type=entity_type)


def make_client(payload: dict, prompt_tokens: int = 0, completion_tokens: int = 0) -> MagicMock:
    """A client that answers every call with the same payload."""
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def sent_prompt(client: MagicMock) -> str:
    return client.chat.completions.create.await_args.kwargs["messages"][0]["content"]


class TestOfferedVocabulary:
    def test_location_npc_pair_offers_located_in_one_way_only(self):
        """The brief's worked example. LOCATED_IN's range is a container, so a
        person cannot be one; MEMBER_OF needs a FACTION and neither side is."""
        options = offered_options(pair(a_name="Chapel", a_type="LOCATION",
                                       b_name="Donavich", b_type="NPC"))

        rendered = {(source, rel.value, target) for source, target, rel in options}
        assert ("Donavich", "LOCATED_IN", "Chapel") in rendered
        assert ("Chapel", "LOCATED_IN", "Donavich") not in rendered
        assert not [option for option in rendered if option[1] == "MEMBER_OF"]

    def test_every_offered_option_satisfies_the_table(self):
        """Swept over every ordered pair of canon entity types, so a widening
        that let an illegal option through cannot hide in an untested corner."""
        for a_type in CANON_ENTITY_TYPES:
            for b_type in CANON_ENTITY_TYPES:
                subject = pair(a_type=a_type.value, b_type=b_type.value)
                for source, target, rel in offered_options(subject):
                    domain, range_ = RELATIONSHIP_DOMAIN_RANGE[rel]
                    source_type = a_type if source == subject.a_name else b_type
                    target_type = b_type if target == subject.b_name else a_type
                    assert source_type in domain, f"{source_type} may not be {rel.value}'s source"
                    assert target_type in range_, f"{target_type} may not be {rel.value}'s target"

    def test_every_legal_option_is_offered(self):
        """The other half: offering a subset would silently narrow the choice
        and make a `NONE` look like a decline when it was an unavailable answer."""
        subject = pair(a_type="NPC", b_type="NPC")
        offered = {(source, target, rel) for source, target, rel in offered_options(subject)}

        for rel in legal_relations(frozenset({EntityType.NPC}), frozenset({EntityType.NPC})):
            assert (subject.a_name, subject.b_name, rel) in offered
            assert (subject.b_name, subject.a_name, rel) in offered

    def test_an_ambiguous_endpoint_type_admits_what_either_type_admits(self):
        """A name carrying two types is a measured occurrence in this corpus.
        Forbidding what only one of them admits would decline a relation the
        edge may well be about -- the `constraints._fits` rule."""
        options = offered_options(pair(a_name="Ireena", a_type="LORE|NPC",
                                       b_name="Ismark", b_type="NPC"))

        assert ("Ireena", "Ismark", RelationshipType.RELATED_TO) in options

    def test_an_untyped_endpoint_is_unconstrained_not_forbidden(self):
        options = offered_options(pair(a_name="Ismark", a_type="NPC",
                                       b_name="Something", b_type=""))

        assert options, "an untyped endpoint must not empty the vocabulary"

    def test_every_offered_relation_carries_its_gloss_in_the_prompt(self):
        """A bare type name does not say which endpoint is which; the gloss does,
        and direction is one of the two things being re-decided."""
        subject = pair(a_type="NPC", b_type="NPC")

        prompt = render_prompt([subject])

        for _, _, rel in offered_options(subject):
            assert RELATIONSHIP_GLOSS[rel] in prompt

    def test_none_is_offered_for_every_item(self):
        prompt = render_prompt([pair(), pair(a_name="Strahd", b_name="Ireena", b_type="NPC")])

        assert prompt.count("- NONE") == 2

    def test_the_answer_form_is_exactly_how_the_option_is_offered(self):
        """One wire form, not two. A structured triple was tried first and the
        model packed the whole rendered option into one field instead, which is
        why validation is an exact match on the string it was shown."""
        subject = pair(a_type="NPC", b_type="NPC")
        prompt = render_prompt([subject])

        for source, target, rel in offered_options(subject):
            assert render_option(source, target, rel) in prompt

    def test_options_are_deterministic(self):
        subject = pair(a_type="NPC", b_type="NPC")

        assert offered_options(subject) == offered_options(subject)
        assert offered_options(subject) == sorted(
            offered_options(subject), key=lambda o: (o[2].value, o[0], o[1])
        )


class TestNoAnchoring:
    def test_pair_carries_no_relationship_type_field(self):
        """The structural guarantee behind the whole comparison: a prompt cannot
        render what the dataclass cannot hold."""
        fields = set(Pair.__dataclass_fields__)

        assert "rel_type" not in fields
        assert not [name for name in fields if "rel" in name.lower()]

    def test_edges_differing_only_in_rel_type_render_the_same_prompt(self):
        """The real anti-anchoring property. Asserting merely that the prompt
        omits the string would pass for the wrong reason -- a legal type appears
        in the options anyway."""
        nodes = [node("Ismark", "NPC"), node("Ireena", "NPC")]
        knows, related = pairs_from_edges(
            nodes, [edge("Ismark", "KNOWS", "Ireena"), edge("Ismark", "RELATED_TO", "Ireena")]
        )

        assert knows == related
        assert render_prompt([knows]) == render_prompt([related])

    def test_an_edge_and_its_reverse_render_the_same_prompt(self):
        """Direction is re-decided, so it must not be inherited -- including as
        the ORDER the two endpoints and their options are listed in."""
        nodes = [node("Ismark", "NPC"), node("Ireena", "NPC")]
        forward, backward = pairs_from_edges(
            nodes, [edge("Ismark", "KNOWS", "Ireena"), edge("Ireena", "KNOWS", "Ismark")]
        )

        assert forward == backward
        assert render_prompt([forward]) == render_prompt([backward])

    def test_the_prompt_omits_a_rel_type_the_endpoints_forbid(self):
        """The brief's literal test, on a case where it is satisfiable: one of
        the five diagnosed failures types an NPC/LOCATION pair GAVE_QUEST, which
        needs a QUEST target and so is never an option here."""
        nodes = [node("Rahadin", "NPC"), node("Dining Hall", "LOCATION")]
        (subject,) = pairs_from_edges(
            nodes, [edge("Rahadin", "GAVE_QUEST", "Dining Hall",
                         evidence="He leads the characters to the dining hall (area K10).")]
        )

        prompt = render_prompt([subject])

        assert "GAVE_QUEST" not in prompt
        assert "He leads the characters to the dining hall" in prompt

    def test_canonical_ordering_is_alphabetical_not_the_edges(self):
        nodes = [node("Ismark", "NPC"), node("Ireena", "NPC")]

        (subject,) = pairs_from_edges(nodes, [edge("Ismark", "KNOWS", "Ireena")])

        assert (subject.a_name, subject.b_name) == ("Ireena", "Ismark")


class TestPairsFromEdges:
    def test_endpoint_types_come_from_the_candidate_nodes(self):
        nodes = [node("Ismark", "NPC"), node("Vallaki", "LOCATION")]

        (subject,) = pairs_from_edges(nodes, [edge("Ismark", "TRAVELED_TO", "Vallaki")])

        assert {subject.a_type, subject.b_type} == {"NPC", "LOCATION"}

    def test_a_name_carrying_two_types_records_both(self):
        nodes = [node("Ireena", "NPC"), node("Ireena", "LORE"), node("Ismark", "NPC")]

        (subject,) = pairs_from_edges(nodes, [edge("Ismark", "KNOWS", "Ireena")])

        assert subject.a_type == "LORE|NPC"

    def test_an_endpoint_no_node_typed_is_empty_not_dropped(self):
        (subject,) = pairs_from_edges([node("Ismark", "NPC")], [edge("Ismark", "KNOWS", "Ghost")])

        assert (subject.a_name, subject.a_type) == ("Ghost", "")

    def test_types_resolve_case_insensitively(self):
        nodes = [node("ISMARK", "NPC"), node("Vallaki", "LOCATION")]

        (subject,) = pairs_from_edges(nodes, [edge("Ismark", "TRAVELED_TO", "Vallaki")])

        assert (subject.a_name, subject.a_type) == ("Ismark", "NPC")

    def test_one_pair_per_edge_in_edge_order(self):
        nodes = [node("A", "NPC"), node("B", "NPC"), node("C", "NPC")]
        edges = [edge("A", "KNOWS", "B"), edge("C", "KNOWS", "B")]

        pairs = pairs_from_edges(nodes, edges)

        assert [(p.a_name, p.b_name) for p in pairs] == [("A", "B"), ("B", "C")]

    def test_evidence_and_provenance_travel_with_the_pair(self):
        nodes = [node("Ismark", "NPC"), node("Vallaki", "LOCATION")]
        source_edge = edge(
            "Ismark", "TRAVELED_TO", "Vallaki",
            evidence="He wants to escort Ireena to Vallaki.",
            section_heading="E2. Blood of the Vine Tavern",
            chapter_slug="chapter-3-the-village-of-barovia",
            section_index=7,
        )

        (subject,) = pairs_from_edges(nodes, [source_edge])

        assert subject.evidence == "He wants to escort Ireena to Vallaki."
        assert subject.section_heading == "E2. Blood of the Vine Tavern"
        assert subject.chapter_slug == "chapter-3-the-village-of-barovia"
        assert subject.section_index == 7


class TestTypeRendering:
    def test_round_trips(self):
        types = frozenset({EntityType.NPC, EntityType.LORE})

        assert parse_types(render_types(types)) == types

    def test_an_unknown_type_name_is_dropped_not_guessed(self):
        assert parse_types("NPC|WIDGET") == frozenset({EntityType.NPC})

    def test_the_empty_string_is_untyped(self):
        assert parse_types("") == frozenset()


class TestSelfPairsAreRejectedBeforeTheModelSeesThem:
    """`Helga Ruvak -IDENTITY_OF-> Helga Ruvak` survived the first measured run
    and shipped in its fabrication sample. No relation in this ontology says
    anything by relating a thing to itself, and the failure class has been known
    on this project since its first fabrication check."""

    def test_a_self_pair_is_offered_nothing(self):
        assert offered_options(pair(a_name="Helga Ruvak", a_type="NPC",
                                    b_name="Helga Ruvak", b_type="NPC")) == []

    def test_the_match_is_on_the_shared_name_fold(self):
        """An extractor that emitted a differently-cased or padded spelling has
        still produced a self-loop."""
        assert is_self_pair(pair(a_name="Strahd", a_type="NPC",
                                 b_name="  strahd ", b_type="NPC"))
        assert offered_options(pair(a_name="Strahd", a_type="NPC",
                                    b_name="  strahd ", b_type="NPC")) == []

    def test_two_different_entities_of_one_type_are_not_a_self_pair(self):
        subject = pair(a_name="Ismark", a_type="NPC", b_name="Ireena", b_type="NPC")

        assert not is_self_pair(subject)
        assert offered_options(subject)

    @pytest.mark.asyncio
    async def test_a_self_pair_is_declined_without_a_call(self):
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify(
            [pair(a_name="Helga Ruvak", a_type="NPC", b_name="Helga Ruvak", b_type="NPC")]
        )

        client.chat.completions.create.assert_not_awaited()
        assert decisions == [[Decision("", "", NONE_RELATION, "")]]
        assert classifier.self_loops == 1
        assert classifier.failures == 0

    @pytest.mark.asyncio
    async def test_it_is_counted_apart_from_the_tables_declines(self):
        """One is a fact about the NAMES, the other about the TYPE TABLE.
        Summing them would describe neither."""
        self_pair = pair(a_name="Helga", a_type="NPC", b_name="Helga", b_type="NPC")
        untypeable = pair(a_name="Curse", a_type="LORE", b_name="Mists", b_type="LORE")
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([self_pair, untypeable])

        assert (classifier.self_loops, classifier.no_legal_relation) == (1, 1)

    @pytest.mark.asyncio
    async def test_a_self_pair_never_reaches_a_rendered_prompt(self):
        self_pair = pair(a_name="Helga Ruvak", a_type="NPC",
                         b_name="Helga Ruvak", b_type="NPC")
        client = make_client({"answers": [{"n": 1, "relations": ["NONE"]}]})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([self_pair, pair()])

        assert "Helga Ruvak" not in sent_prompt(client)


class TestSeveralRelationsPerPair:
    """Of the three golden edges the first run lost, one was a single sentence
    stating TWO true relations where the design permitted one answer. The cap is
    low and the prompt demands each relation be independently stated, because
    the obvious failure mode is a model filling the slots."""

    @pytest.mark.asyncio
    async def test_two_independently_stated_relations_both_survive(self):
        subject = pair(a_name="Ireena", a_type="NPC", b_name="Ismark", b_type="NPC")
        client = make_client({"answers": [{
            "n": 1,
            "relations": ["Ismark -RELATED_TO-> Ireena", "Ismark -GUARDS-> Ireena"],
            "confidence": "clear",
        }]})
        classifier = RelationClassifier(client=client, model="test-model")

        (decisions,) = await classifier.classify([subject])

        assert decisions == [
            Decision("Ismark", "Ireena", "RELATED_TO", "clear"),
            Decision("Ismark", "Ireena", "GUARDS", "clear"),
        ]

    @pytest.mark.asyncio
    async def test_more_than_the_cap_is_truncated_and_recorded(self):
        """`capped` is the evidence for whether the CAP or the EVIDENCE decides
        how many relations a pair carries."""
        subject = pair(a_name="Ireena", a_type="NPC", b_name="Ismark", b_type="NPC")
        client = make_client({"answers": [{
            "n": 1,
            "relations": ["Ismark -RELATED_TO-> Ireena", "Ismark -GUARDS-> Ireena",
                          "Ismark -KNOWS-> Ireena"],
            "confidence": "clear",
        }]})
        classifier = RelationClassifier(client=client, model="test-model", max_relations=2)

        (decisions,) = await classifier.classify([subject])

        assert len(decisions) == 2
        assert classifier.capped == 1

    @pytest.mark.asyncio
    async def test_within_the_cap_nothing_is_recorded_as_capped(self):
        client = make_client({"answers": [
            {"n": 1, "relations": ["Ismark -TRAVELED_TO-> Vallaki"], "confidence": "clear"}
        ]})
        classifier = RelationClassifier(client=client, model="test-model", max_relations=2)

        await classifier.classify([pair()])

        assert classifier.capped == 0

    @pytest.mark.asyncio
    async def test_the_same_relation_twice_is_one_relation(self):
        client = make_client({"answers": [{
            "n": 1,
            "relations": ["Ismark -TRAVELED_TO-> Vallaki", "ISMARK -TRAVELED_TO-> VALLAKI"],
            "confidence": "clear",
        }]})
        classifier = RelationClassifier(client=client, model="test-model")

        (decisions,) = await classifier.classify([pair()])

        assert decisions == [Decision("Ismark", "Vallaki", "TRAVELED_TO", "clear")]
        assert classifier.capped == 0

    @pytest.mark.asyncio
    async def test_an_empty_relation_list_is_a_decline_not_a_failure(self):
        """"I chose nothing" is unambiguous in meaning. Counting it as a failure
        would understate the decline rate, which is the number this experiment
        turns on."""
        client = make_client({"answers": [{"n": 1, "relations": [], "confidence": "clear"}]})
        classifier = RelationClassifier(client=client, model="test-model")

        (decisions,) = await classifier.classify([pair()])

        assert decisions == [Decision("", "", NONE_RELATION, "clear")]
        assert classifier.failures == 0

    @pytest.mark.asyncio
    async def test_none_beside_a_real_relation_takes_the_relation(self):
        """A contradiction in the answer. The model named something specific;
        reading that as a decline would discard a positive answer it gave."""
        client = make_client({"answers": [{
            "n": 1,
            "relations": ["NONE", "Ismark -TRAVELED_TO-> Vallaki"],
            "confidence": "clear",
        }]})
        classifier = RelationClassifier(client=client, model="test-model")

        (decisions,) = await classifier.classify([pair()])

        assert decisions == [Decision("Ismark", "Vallaki", "TRAVELED_TO", "clear")]

    def test_the_prompt_states_the_cap_it_will_enforce(self):
        prompt = render_prompt([pair()], max_relations=2)

        assert "up to 2" in prompt

    def test_the_worked_example_does_not_teach_a_measured_case(self):
        """The first draft used `Ismark RELATED_TO/GUARDS Ireena` -- one of the
        three golden edges the previous run LOST, and the exact case this change
        exists to recover. Shipping that would have made its recovery worthless
        as evidence."""
        prompt = render_prompt([pair(a_name="Zed", a_type="NPC", b_name="Zeb", b_type="NPC")])
        instructions = prompt.split("--- ITEMS ---")[0]

        for corpus_name in ("Ismark", "Ireena", "Strahd", "Vallaki", "Morgantha", "Rahadin"):
            assert corpus_name not in instructions


class TestNoLegalRelation:
    @pytest.mark.asyncio
    async def test_a_pair_admitting_nothing_is_declined_without_a_call(self):
        """LORE stands in no domain in the table, so two LORE entities admit
        nothing in either direction. Asking the model would be asking it to pick
        from an empty list."""
        subject = pair(a_name="Curse", a_type="LORE", b_name="Mists", b_type="LORE")
        assert offered_options(subject) == [], "test premise: no relation is legal here"
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify([subject])

        client.chat.completions.create.assert_not_awaited()
        assert decisions == [[Decision("", "", NONE_RELATION, "")]]
        assert classifier.no_legal_relation == 1
        assert classifier.failures == 0
        assert classifier.calls == 0

    @pytest.mark.asyncio
    async def test_it_is_counted_apart_from_the_models_own_declines(self):
        """A decline by the TABLE is not evidence the model declines. Summing
        them would inflate the decline rate the experiment turns on."""
        askable = pair()
        unaskable = pair(a_name="Curse", a_type="LORE", b_name="Mists", b_type="LORE")
        client = make_client({"answers": [{"n": 1, "rel_type": "NONE"}]})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([unaskable, askable])

        assert classifier.no_legal_relation == 1
        assert classifier.calls == 1

    @pytest.mark.asyncio
    async def test_the_askable_pairs_still_line_up_after_one_is_skipped(self):
        unaskable = pair(a_name="Curse", a_type="LORE", b_name="Mists", b_type="LORE")
        first = pair(a_name="Ireena", a_type="NPC", b_name="Ismark", b_type="NPC")
        second = pair(a_name="Barovia", a_type="LOCATION", b_name="Church", b_type="LOCATION")
        client = make_client({"answers": [
            {"n": 1, "relations": ["Ireena -KNOWS-> Ismark"], "confidence": "clear"},
            {"n": 2, "relations": ["Church -LOCATED_IN-> Barovia"], "confidence": "clear"},
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify([first, unaskable, second])

        assert decisions[0] == [Decision("Ireena", "Ismark", "KNOWS", "clear")]
        assert decisions[1] == [Decision("", "", NONE_RELATION, "")]
        assert decisions[2] == [Decision("Church", "Barovia", "LOCATED_IN", "clear")]


class TestParsing:
    @pytest.mark.asyncio
    async def test_none_parses_to_empty_endpoints(self):
        client = make_client({"answers": [{"n": 1, "relations": ["NONE"], "confidence": "unsure"}]})
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify([pair()])

        assert decisions == [[Decision("", "", NONE_RELATION, "unsure")]]
        assert classifier.failures == 0

    @pytest.mark.asyncio
    async def test_a_batch_answering_seven_of_ten_is_not_silently_truncated(self):
        """The corruption this guards is positional realignment: reading the
        answer list in order would move items 8-10's decisions onto pairs 8-10
        while items 8-10 were never answered, and the result would look like a
        low agreement rate rather than a bug."""
        pairs = [
            pair(a_name=f"NPC{i:02d}", a_type="NPC", b_name=f"Town{i:02d}", b_type="LOCATION")
            for i in range(10)
        ]
        client = make_client({"answers": [
            {"n": n, "relations": [f"NPC{n - 1:02d} -TRAVELED_TO-> Town{n - 1:02d}"],
             "confidence": "clear"}
            for n in (1, 2, 3, 5, 7, 9, 10)
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify(pairs)

        answered = {1, 2, 3, 5, 7, 9, 10}
        for position, decision in enumerate(decisions, start=1):
            if position in answered:
                assert decision == [Decision(
                    f"NPC{position - 1:02d}", f"Town{position - 1:02d}", "TRAVELED_TO", "clear"
                )]
            else:
                assert decision == [Decision("", "", NO_ANSWER, "")]
        assert classifier.failures == 3

    @pytest.mark.asyncio
    async def test_a_missing_answer_is_not_recorded_as_a_decline(self):
        """The decline rate is the experiment's precision signal. A silence
        counted as a decline would manufacture that signal out of failures."""
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model")

        ((decision,),) = await classifier.classify([pair()])

        assert decision.rel_type == NO_ANSWER
        assert decision.rel_type != NONE_RELATION
        assert classifier.failures == 1

    @pytest.mark.asyncio
    async def test_one_malformed_answer_does_not_corrupt_its_neighbours(self):
        pairs = [
            pair(a_name="Ismark", a_type="NPC", b_name="Vallaki", b_type="LOCATION"),
            pair(a_name="Ireena", a_type="NPC", b_name="Krezk", b_type="LOCATION"),
            pair(a_name="Doru", a_type="NPC", b_name="Barovia", b_type="LOCATION"),
        ]
        client = make_client({"answers": [
            {"n": 1, "relations": ["Ismark -TRAVELED_TO-> Vallaki"], "confidence": "clear"},
            {"n": 2, "relations": "not a list"},
            {"n": 3, "relations": ["Doru -LOCATED_IN-> Barovia"], "confidence": "implied"},
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify(pairs)

        assert decisions[0] == [Decision("Ismark", "Vallaki", "TRAVELED_TO", "clear")]
        assert decisions[1] == [Decision("", "", NO_ANSWER, "")]
        assert decisions[2] == [Decision("Doru", "Barovia", "LOCATED_IN", "implied")]
        assert classifier.failures == 1

    @pytest.mark.asyncio
    async def test_a_relation_that_was_not_offered_is_a_non_answer(self):
        """Not a quiet NONE: recording it as a decline would let an answer the
        ontology forbids feed the precision number it was meant to be caught by."""
        client = make_client({"answers": [
            {"n": 1, "relations": ["Vallaki -LOCATED_IN-> Ismark"], "confidence": "clear"}
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        ((decision,),) = await classifier.classify([pair()])

        assert decision == Decision("", "", NO_ANSWER, "")
        assert classifier.failures == 1

    @pytest.mark.asyncio
    async def test_an_endpoint_that_was_not_in_the_item_is_a_non_answer(self):
        client = make_client({"answers": [
            {"n": 1, "relations": ["Ismark -TRAVELED_TO-> Krezk"], "confidence": "clear"}
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        ((decision,),) = await classifier.classify([pair()])

        assert decision == Decision("", "", NO_ANSWER, "")
        assert classifier.failures == 1

    @pytest.mark.asyncio
    async def test_the_model_may_flip_the_direction(self):
        """The point of offering both directions -- a reversal must be
        expressible, since a reversal is one of the diagnosed failures."""
        subject = pair(a_name="Strahd", a_type="NPC", b_name="Vampire Spawn", b_type="MONSTER")
        client = make_client({"answers": [
            {"n": 1, "relations": ["Vampire Spawn -SERVES-> Strahd"], "confidence": "clear"}
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        ((decision,),) = await classifier.classify([subject])

        assert decision == Decision("Vampire Spawn", "Strahd", "SERVES", "clear")

    @pytest.mark.asyncio
    async def test_endpoint_names_are_matched_case_insensitively(self):
        client = make_client({"answers": [
            {"n": 1, "relations": ["  ismark   -TRAVELED_TO->  VALLAKI "], "confidence": "Clear"}
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        ((decision,),) = await classifier.classify([pair()])

        assert decision == Decision("Ismark", "Vallaki", "TRAVELED_TO", "clear")

    @pytest.mark.asyncio
    async def test_a_duplicated_number_does_not_answer_twice(self):
        client = make_client({"answers": [
            {"n": 1, "relations": ["NONE"], "confidence": "clear"},
            {"n": 1, "relations": ["Ismark -TRAVELED_TO-> Vallaki"]},
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify([pair()])

        assert decisions == [[Decision("", "", NONE_RELATION, "clear")]]

    @pytest.mark.asyncio
    async def test_a_payload_with_no_answers_list_fails_every_pair(self):
        client = make_client({"result": "sorry"})
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify([pair(), pair(a_name="Doru")])

        assert [d[0].rel_type for d in decisions] == [NO_ANSWER, NO_ANSWER]
        assert classifier.failures == 2

    @pytest.mark.asyncio
    async def test_an_unnumbered_answer_is_ignored_rather_than_positioned(self):
        client = make_client({"answers": [
            {"relations": ["Ismark -TRAVELED_TO-> Vallaki"]}
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        ((decision,),) = await classifier.classify([pair()])

        assert decision.rel_type == NO_ANSWER


class TestTheThreeKindsOfNonAnswer:
    """A run problem, a model problem, and the constraint working are three
    different events that all produce no edge. Summing them into one number
    would hide which one happened, and the third is not a defect at all.

    `failures` counts PAIRS; `off_vocabulary` counts RELATIONS, because with
    several relations allowed per pair one can be refused while another stands.
    Adding them would double-count the pair that lost only one of two."""

    @pytest.mark.asyncio
    async def test_a_failed_call_is_counted_as_a_call_failure(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("429"))
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([pair()])

        assert (classifier.call_failures, classifier.unanswered, classifier.unusable) == (
            1, 0, 0,
        )

    @pytest.mark.asyncio
    async def test_a_skipped_number_is_counted_as_unanswered(self):
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([pair()])

        assert (classifier.call_failures, classifier.unanswered, classifier.unusable) == (
            0, 1, 0,
        )

    @pytest.mark.asyncio
    async def test_relations_that_is_not_a_list_is_unreadable(self):
        client = make_client({"answers": [{"n": 1, "relations": "Ismark -KNOWS-> Vallaki"}]})
        classifier = RelationClassifier(client=client, model="test-model")

        ((decision,),) = await classifier.classify([pair()])

        assert decision.rel_type == NO_ANSWER
        assert classifier.unanswered == 1

    @pytest.mark.asyncio
    async def test_an_answer_off_the_offered_list_is_counted_apart(self):
        """This one is the TYPE CONSTRAINT BITING, not a defect: the model chose
        a relation the endpoint types forbid and was refused. Its size is the
        evidence for how much work the constraint does."""
        client = make_client({"answers": [
            {"n": 1, "relations": ["Vallaki -LOCATED_IN-> Ismark"], "confidence": "clear"}
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([pair()])

        assert classifier.off_vocabulary == 1
        assert (classifier.call_failures, classifier.unanswered, classifier.unusable) == (
            0, 0, 1,
        )

    @pytest.mark.asyncio
    async def test_a_refused_relation_does_not_take_its_valid_sibling_with_it(self):
        """The reason `off_vocabulary` counts relations and `failures` counts
        pairs. One bad name in a two-relation answer must cost that relation
        and nothing else."""
        client = make_client({"answers": [{
            "n": 1,
            "relations": ["Ismark -TRAVELED_TO-> Vallaki", "Vallaki -LOCATED_IN-> Ismark"],
            "confidence": "clear",
        }]})
        classifier = RelationClassifier(client=client, model="test-model")

        (decisions,) = await classifier.classify([pair()])

        assert decisions == [Decision("Ismark", "Vallaki", "TRAVELED_TO", "clear")]
        assert classifier.off_vocabulary == 1
        assert classifier.failures == 0

    @pytest.mark.asyncio
    async def test_failures_is_their_sum(self):
        client = make_client({"answers": [
            {"n": 1, "relations": ["Vallaki -LOCATED_IN-> Ismark"]},
        ]})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([pair(), pair(a_name="Doru"), pair(a_name="Erik")])

        assert classifier.failures == 3
        assert classifier.failures == (
            classifier.call_failures + classifier.unanswered + classifier.unusable
        )

    @pytest.mark.asyncio
    async def test_a_decline_is_not_any_kind_of_failure(self):
        client = make_client({"answers": [{"n": 1, "relations": ["NONE"]}]})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([pair()])

        assert classifier.failures == 0


class TestFailureHandling:
    @pytest.mark.asyncio
    async def test_an_api_error_fails_the_batch_without_raising(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("429"))
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify([pair(), pair(a_name="Doru")])

        assert [d[0].rel_type for d in decisions] == [NO_ANSWER, NO_ANSWER]
        assert classifier.failures == 2
        assert classifier.calls == 0

    @pytest.mark.asyncio
    async def test_unparseable_json_fails_the_batch(self):
        message = MagicMock()
        message.content = "not json"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)
        classifier = RelationClassifier(client=client, model="test-model")

        decisions = await classifier.classify([pair()])

        assert decisions[0][0].rel_type == NO_ANSWER
        assert classifier.failures == 1

    @pytest.mark.asyncio
    async def test_one_failed_batch_leaves_the_others_answered(self):
        good = {"answers": [
            {"n": n, "relations": ["Ismark -TRAVELED_TO-> Vallaki"], "confidence": "clear"}
            for n in range(1, 3)
        ]}
        message = MagicMock()
        message.content = json.dumps(good)
        choice = MagicMock()
        choice.message = message
        ok = MagicMock()
        ok.choices = [choice]
        ok.usage = MagicMock(prompt_tokens=0, completion_tokens=0)
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=[RuntimeError("429"), ok])
        classifier = RelationClassifier(client=client, model="test-model", batch_size=2)

        decisions = await classifier.classify([pair()] * 4)

        assert [d[0].rel_type for d in decisions] == [NO_ANSWER, NO_ANSWER,
                                                      "TRAVELED_TO", "TRAVELED_TO"]
        assert classifier.failures == 2


class TestBatchingAndCost:
    @pytest.mark.asyncio
    async def test_pairs_are_split_into_batches_of_the_configured_size(self):
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model", batch_size=10)

        await classifier.classify([pair()] * 25)

        assert client.chat.completions.create.await_count == 3
        assert classifier.calls == 3

    @pytest.mark.asyncio
    async def test_every_pair_gets_exactly_one_decision_in_input_order(self):
        pairs = [
            pair(a_name=f"NPC{i:02d}", a_type="NPC", b_name=f"Town{i:02d}", b_type="LOCATION")
            for i in range(7)
        ]
        client = make_client({"answers": [
            {"n": n, "relations": ["NONE"], "confidence": "clear"} for n in range(1, 8)
        ]})
        classifier = RelationClassifier(client=client, model="test-model", batch_size=3)

        decisions = await classifier.classify(pairs)

        assert len(decisions) == len(pairs)
        assert all(d == [Decision("", "", NONE_RELATION, "clear")] for d in decisions)

    @pytest.mark.asyncio
    async def test_token_usage_accumulates_across_calls(self):
        client = make_client({"answers": []}, prompt_tokens=1200, completion_tokens=300)
        classifier = RelationClassifier(client=client, model="test-model", batch_size=1)

        await classifier.classify([pair(), pair()])

        assert classifier.input_tokens == 2400
        assert classifier.output_tokens == 600

    @pytest.mark.asyncio
    async def test_the_request_pins_temperature_and_seed(self):
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([pair()])

        kwargs = client.chat.completions.create.await_args.kwargs
        assert kwargs["temperature"] == 0.0
        assert kwargs["seed"] == EXTRACTION_SEED
        assert kwargs["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_the_prompt_actually_sent_carries_the_items(self):
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model")

        await classifier.classify([pair()])

        prompt = sent_prompt(client)
        assert "He wants to escort Ireena to Vallaki." in prompt
        assert "1. Ismark (NPC) and Vallaki (LOCATION)" in prompt

    @pytest.mark.asyncio
    async def test_an_empty_pair_list_costs_nothing(self):
        client = make_client({"answers": []})
        classifier = RelationClassifier(client=client, model="test-model")

        assert await classifier.classify([]) == []
        client.chat.completions.create.assert_not_awaited()
