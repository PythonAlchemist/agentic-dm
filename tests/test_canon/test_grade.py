"""Scoring candidates against the golden set.

Recall is computable; precision is not. The golden set lists 18 nodes for
chapter 3, but the chapter contains far more nameable things, so an unmatched
candidate is usually a legitimate entity the key omits. Scoring precision here
would punish an extractor for being thorough.
"""

import pytest

from backend.canon.grade import ceiling, grade, names_match, normalize_name
from backend.canon.models import CandidateEdge, CandidateNode


def golden(nodes=None, edges=None) -> dict:
    return {"nodes": nodes or [], "edges": edges or []}


def gnode(name, entity_type="NPC", **kw):
    """A golden node whose id encodes its own type -- `cos:<type>:<slug>`.

    The type segment is the one the matcher reads (see `golden_entity_type`), so a
    fixture whose id said `npc` while its `entity_type` said QUEST would be
    self-contradictory and would grade against the wrong type.
    """
    return {
        "id": f"cos:{entity_type.lower()}:{name.lower()}",
        "name": name,
        "entity_type": entity_type,
        **kw,
    }


def gedge(source, target, rel_type):
    return {"source": source, "target": target, "type": rel_type}


def cnode(name, entity_type="NPC"):
    return CandidateNode(name=name, entity_type=entity_type)


def cedge(source, target, rel_type):
    return CandidateEdge(source_name=source, target_name=target, rel_type=rel_type)


class TestNormalizeName:
    def test_case_and_punctuation_are_ignored(self):
        assert normalize_name("Ismark the Lesser") == normalize_name("ismark the lesser")
        assert normalize_name("Bildrath's Mercantile") == normalize_name("Bildraths Mercantile")

    def test_leading_article_is_dropped(self):
        assert normalize_name("The Village of Barovia") == normalize_name("Village of Barovia")

    def test_whitespace_is_collapsed(self):
        assert normalize_name("Blood  on   the Vine") == normalize_name("Blood on the Vine")


class TestNodeRecall:
    def test_perfect_extraction_scores_one(self):
        g = golden(nodes=[gnode("Ireena"), gnode("Ismark")])
        report = grade([cnode("Ireena"), cnode("Ismark")], [], g)

        assert report.node_recall == 1.0
        assert report.missing_nodes == []

    def test_one_miss_of_four_scores_exactly_three_quarters(self):
        g = golden(nodes=[gnode(n) for n in ("A", "B", "C", "D")])
        report = grade([cnode(n) for n in ("A", "B", "C")], [], g)

        assert report.node_recall == 0.75
        assert report.missing_nodes == ["D"]

    def test_alias_counts_as_a_match(self):
        """An extractor that says "Ismark" should not be marked wrong because the
        key says "Ismark Kolyanovich"."""
        g = golden(nodes=[gnode("Ismark Kolyanovich", aliases=["Ismark the Lesser"])])
        report = grade([cnode("Ismark the Lesser")], [], g)

        assert report.node_recall == 1.0

    def test_unmatched_candidates_are_listed_not_scored(self):
        g = golden(nodes=[gnode("Ireena")])
        report = grade([cnode("Ireena"), cnode("A Barkeep")], [], g)

        assert report.node_recall == 1.0, "an extra candidate must not reduce recall"
        assert report.unmatched_nodes == ["A Barkeep"]

    def test_empty_golden_scores_one_not_zero_division(self):
        report = grade([cnode("Ireena")], [], golden())

        assert report.node_recall == 1.0
        assert report.unmatched_nodes == ["Ireena"]


class TestEdgeRecall:
    def test_edge_matches_on_type_and_both_endpoints(self):
        g = golden(edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
                   nodes=[gnode("A"), gnode("B")])
        report = grade([cnode("A"), cnode("B")], [cedge("A", "B", "KNOWS")], g)

        assert report.edge_recall == 1.0

    def test_wrong_type_is_not_a_match(self):
        g = golden(edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
                   nodes=[gnode("A"), gnode("B")])
        report = grade([], [cedge("A", "B", "SEEKS")], g)

        assert report.edge_recall == 0.0
        assert len(report.missing_edges) == 1

    def test_reversed_direction_is_not_a_match(self):
        g = golden(edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
                   nodes=[gnode("A"), gnode("B")])
        report = grade([], [cedge("B", "A", "KNOWS")], g)

        assert report.edge_recall == 0.0

    def test_edge_endpoint_reachable_only_via_alias(self):
        """A candidate edge naming an endpoint by its alias must still match --
        `by_id` values come from `_golden_node_names`, which folds in aliases."""
        g = golden(
            edges=[gedge("cos:npc:ismark kolyanovich", "cos:npc:b", "KNOWS")],
            nodes=[gnode("Ismark Kolyanovich", aliases=["Ismark the Lesser"]), gnode("B")],
        )
        report = grade(
            [cnode("Ismark the Lesser"), cnode("B")],
            [cedge("Ismark the Lesser", "B", "KNOWS")],
            g,
        )

        assert report.edge_recall == 1.0

    def test_unmatched_edges_are_listed_not_scored(self):
        """Fabrication is most likely among the ~139 extracted edges, not the
        ~166 nodes -- the real chapter-3 run contains "Ireena Kolyana
        -GUARDS-> Castle Ravenloft". The report must carry the candidate
        edges that scored no golden match so a human can spot-check them; an
        extra candidate edge must not reduce edge_recall either."""
        g = golden(edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
                   nodes=[gnode("A"), gnode("B")])
        report = grade(
            [cnode("A"), cnode("B"), cnode("Ireena Kolyana"), cnode("Castle Ravenloft")],
            [cedge("A", "B", "KNOWS"), cedge("Ireena Kolyana", "Castle Ravenloft", "GUARDS")],
            g,
        )

        assert report.edge_recall == 1.0
        assert report.unmatched_edges == ["Ireena Kolyana -GUARDS-> Castle Ravenloft"]


class TestCollisions:
    def test_two_golden_names_folding_to_the_same_form_are_flagged(self):
        g = golden(nodes=[gnode("The Vine"), gnode("Vine")])
        report = grade([], [], g)

        assert report.collisions != []
        assert any("vine" in c for c in report.collisions)

    def test_no_collisions_when_golden_names_are_distinct(self):
        g = golden(nodes=[gnode("Ireena"), gnode("Ismark")])
        report = grade([], [], g)

        assert report.collisions == []

    def test_collision_between_a_name_and_anothers_alias_is_caught(self):
        g = golden(nodes=[gnode("Vine"), gnode("Blood on the Vine", aliases=["The Vine"])])
        report = grade([], [], g)

        assert report.collisions != []
        assert any("vine" in c for c in report.collisions)

    def test_collision_does_not_move_recall(self):
        g = golden(nodes=[gnode("The Vine"), gnode("Vine")])
        report = grade([cnode("Vine")], [], g)

        assert report.node_recall == 1.0


class TestAgainstTheRealSeed:
    def test_grades_against_the_chapter_three_subset(self):
        import yaml

        from backend.canon.seed_loader import SEED_DIR, extractable_subset

        data = yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())
        subset = extractable_subset(data, "ch3")
        report = grade([], [], subset)

        assert report.node_recall == 0.0
        assert len(report.missing_nodes) == len(subset["nodes"])
        assert "Ireena Kolyana" in report.missing_nodes


class TestSubsetMatching:
    """A shorter name the passage actually used must match the key's fuller form.

    The extractor writes what the book writes. Chapter 3 says "Strahd" far more
    often than "Strahd von Zarovich", and grading the former as a miss measures
    naming convention rather than whether the entity was found.
    """

    def test_shorter_candidate_matches_longer_golden(self):
        assert names_match("Strahd", "Strahd von Zarovich")
        assert names_match("Church", "Church of Barovia")
        assert names_match("Barovia", "Village of Barovia")
        assert names_match("Ismark", "Ismark Kolyanovich")

    def test_longer_candidate_matches_shorter_golden(self):
        """Direction must not matter -- the extractor may be more specific."""
        assert names_match("Ireena Kolyana", "Ireena")

    def test_articles_are_still_folded(self):
        assert names_match("The Church", "Church of Barovia")

    def test_unrelated_names_do_not_match(self):
        assert not names_match("Ismark", "Ireena")
        assert not names_match("Bildrath", "Parriwimple")

    def test_a_shared_generic_token_is_not_enough(self):
        """"Village of Barovia" and "Village of Krezk" share a token and are
        different places. Subset matching must not collapse them."""
        assert not names_match("Village of Krezk", "Village of Barovia")

    def test_typos_do_not_match(self):
        """Deliberate: a transcription typo is a real defect, not naming variance.

        Making the matcher fuzzy enough to absorb "Morgatha" -> "Morgantha" would
        also hide genuine extraction errors.
        """
        assert not names_match("Morgatha", "Morgantha")
        assert not names_match("Blood of the Vine Tavern", "Blood on the Vine Tavern")


class TestSubsetMatchingInGrade:
    def test_recall_counts_a_shorter_candidate(self):
        g = golden(nodes=[gnode("Strahd von Zarovich")])
        report = grade([cnode("Strahd")], [], g)

        assert report.node_recall == 1.0
        assert report.unmatched_nodes == []

    def test_edge_endpoints_use_subset_matching_too(self):
        g = golden(
            nodes=[gnode("Strahd von Zarovich"), gnode("Ireena Kolyana")],
            edges=[gedge("cos:npc:strahd von zarovich", "cos:npc:ireena kolyana", "SEEKS")],
        )
        report = grade(
            [cnode("Strahd"), cnode("Ireena")], [cedge("Strahd", "Ireena", "SEEKS")], g
        )

        assert report.edge_recall == 1.0

    def test_an_ambiguous_candidate_is_reported_as_a_collision(self):
        """If a short name matches two golden entries, that is ambiguity, and the
        harness must say so rather than silently crediting one."""
        g = golden(nodes=[gnode("Strahd von Zarovich"), gnode("Strahd Zombie")])
        report = grade([cnode("Strahd")], [], g)

        assert report.collisions, "an ambiguous candidate must be surfaced"


class TestUnambiguousNodeRecall:
    """This is the guard against the inflation class of defect: `node_recall`
    credits a golden entry from ANY candidate that loosely matches, including one
    that also matches another entry. `node_recall_unambiguous` must not."""

    def test_single_word_candidates_score_high_loose_but_near_zero_unambiguous_recall(self):
        """Reproduces the measured defect: a degenerate extractor emitting only
        words that appear in golden names scores node_recall == 1.0 while
        crediting no entry unambiguously."""
        g = golden(
            nodes=[
                gnode("Village Ireena"),
                gnode("Village Vallaki"),
                gnode("Ireena Vallaki"),
            ]
        )
        candidates = [cnode("Village"), cnode("Ireena"), cnode("Vallaki")]
        report = grade(candidates, [], g)

        assert report.node_recall == 1.0
        assert report.node_recall_unambiguous == 0.0

    def test_an_unambiguous_match_counts_toward_unambiguous_recall(self):
        g = golden(nodes=[gnode("Ireena"), gnode("Ismark")])
        report = grade([cnode("Ireena"), cnode("Ismark")], [], g)

        assert report.node_recall_unambiguous == 1.0

    def test_an_entry_with_both_an_ambiguous_and_unambiguous_witness_counts(self):
        """A single unambiguous witness is enough to credit an entry -- this
        does NOT require every matching candidate to be unambiguous, only
        that at least one is. "Ireena" is ambiguous (it matches both NPCs),
        but "Ireena Kolyana" matches one of them alone, so that entry is
        credited. "Ireena the Cursed" has no unambiguous witness at all, so
        only half of the two entries count.

        Both entries are NPCs deliberately: since matching became type-aware,
        two entries of different types sharing a name are no longer ambiguous
        at all, so a QUEST here would not exercise this path.

        Pinned so a future "require ALL matching candidates to be
        unambiguous" rewrite is caught immediately.
        """
        g = golden(nodes=[gnode("Ireena Kolyana"), gnode("Ireena the Cursed")])
        report = grade([cnode("Ireena"), cnode("Ireena Kolyana")], [], g)

        assert report.node_recall == 1.0
        assert report.node_recall_unambiguous == 0.5

    def test_collision_does_not_move_recall_but_does_move_unambiguous_recall(self):
        """A candidate matching two entries loosely still doesn't hurt the loose
        number (see TestCollisions), but it must not count as unambiguous
        evidence for either."""
        g = golden(nodes=[gnode("Strahd von Zarovich"), gnode("Strahd Zombie")])
        report = grade([cnode("Strahd")], [], g)

        assert report.node_recall == 1.0
        assert report.node_recall_unambiguous == 0.0


class TestTypeAwareMatching:
    """A candidate credits a golden entry only when it is the same KIND of thing.

    Measured: a ~10-line regex scraping capitalized words scored 0.78 unambiguous
    node recall against chapter 3 -- above the tuned three-pass pipeline's 0.72.
    `*_unambiguous` cannot stop that, because it constrains what one candidate
    matches, never how many candidates exist. Nearly every collision in the golden
    set is a TYPE collision (`Vallaki` the LOCATION versus `Escort Ireena to
    Vallaki` the QUEST), so requiring the type to agree removes the credit that
    was being awarded for matching the wrong kind of thing.
    """

    def test_a_location_credits_the_location_and_not_the_quest_named_after_it(self):
        g = golden(
            nodes=[
                gnode("Vallaki", entity_type="LOCATION"),
                gnode("Escort Ireena to Vallaki", entity_type="QUEST"),
            ]
        )
        report = grade([cnode("Vallaki", "LOCATION")], [], g)

        assert report.missing_nodes == ["Escort Ireena to Vallaki"]
        assert report.node_recall == 0.5
        assert report.node_recall_unambiguous == 0.5, (
            "the LOCATION is now credited unambiguously -- the quest it collided "
            "with is a different type and no longer competes"
        )

    def test_type_is_compared_case_insensitively(self):
        g = golden(nodes=[gnode("Vallaki", entity_type="LOCATION")])

        assert grade([cnode("Vallaki", "location")], [], g).node_recall == 1.0

    def test_the_shotgun_in_miniature(self):
        """A scraper that emits every capitalized name under one blanket type can
        only ever credit that type's slice of the key, however many names it
        emits. Under name-only matching this same candidate set scored 1.00."""
        g = golden(
            nodes=[
                gnode("Vallaki", entity_type="LOCATION"),
                gnode("Church of Barovia", entity_type="LOCATION"),
                gnode("Ireena Kolyana", entity_type="NPC"),
                gnode("Donavich", entity_type="NPC"),
                gnode("Escort Ireena to Vallaki", entity_type="QUEST"),
            ]
        )
        shotgun = [
            cnode(n, "LOCATION")
            for n in ("Vallaki", "Church", "Ireena", "Donavich", "Escort", "Barovia")
        ]

        report = grade(shotgun, [], g)

        assert report.node_recall == 0.4, "only the two LOCATION entries can be credited"
        assert sorted(report.missing_nodes) == [
            "Donavich",
            "Escort Ireena to Vallaki",
            "Ireena Kolyana",
        ]

    def test_the_same_names_correctly_typed_still_score_one(self):
        """The control for the shotgun case above: the names are doing no less
        work than before -- it is the type, and only the type, that changed."""
        g = golden(
            nodes=[
                gnode("Vallaki", entity_type="LOCATION"),
                gnode("Ireena Kolyana", entity_type="NPC"),
            ]
        )
        report = grade([cnode("Vallaki", "LOCATION"), cnode("Ireena", "NPC")], [], g)

        assert report.node_recall == 1.0

    def test_an_untyped_candidate_matches_nothing(self):
        """A candidate carrying no entity_type must not fall back to name-only
        matching -- that fallback is exactly the hole this closes."""
        g = golden(nodes=[gnode("Vallaki", entity_type="LOCATION")])
        report = grade([cnode("Vallaki", "")], [], g)

        assert report.node_recall == 0.0
        assert report.unmatched_nodes == ["Vallaki"]

    def test_a_golden_id_with_an_unknown_type_segment_raises(self):
        """A malformed id must not become a wildcard that matches every type."""
        g = golden(nodes=[{"id": "cos:locaton:vallaki", "name": "Vallaki",
                           "entity_type": "LOCATION"}])

        with pytest.raises(ValueError) as exc:
            grade([cnode("Vallaki", "LOCATION")], [], g)

        assert "cos:locaton:vallaki" in str(exc.value)

    def test_a_golden_id_without_three_segments_raises(self):
        g = golden(nodes=[{"id": "vallaki", "name": "Vallaki", "entity_type": "LOCATION"}])

        with pytest.raises(ValueError):
            grade([cnode("Vallaki", "LOCATION")], [], g)


class TestCeiling:
    """The key graded against itself: the best any extractor could ever score.

    Measured before type-aware matching, chapter 3's own golden set scored 0.78
    node / 0.68 edge unambiguous against ITSELF -- four nodes and eight edges
    were uncreditable by construction, and the spec's 0.9 bar was unreachable by
    anything. Nobody could see that without running the experiment.
    """

    def test_a_key_with_no_collisions_has_a_ceiling_of_one(self):
        g = golden(
            nodes=[gnode("Ireena Kolyana"), gnode("Vallaki", entity_type="LOCATION")],
            edges=[gedge("cos:npc:ireena kolyana", "cos:location:vallaki", "TRAVELED_TO")],
        )

        assert ceiling(g) == (1.0, 1.0)

    def test_a_same_type_token_subset_pair_lowers_the_node_ceiling(self):
        """"Vallaki" is a token-subset of "Vallaki Gates" and both are LOCATIONs,
        so each key entry's own exact name matches the other. Neither can ever be
        credited unambiguously, by anyone."""
        g = golden(
            nodes=[
                gnode("Vallaki", entity_type="LOCATION"),
                gnode("Vallaki Gates", entity_type="LOCATION"),
                gnode("Ireena Kolyana"),
                gnode("Donavich"),
            ]
        )

        assert ceiling(g)[0] == 0.5

    def test_the_type_collision_that_used_to_cost_a_node_no_longer_does(self):
        """`Vallaki` the LOCATION against `Escort Ireena to Vallaki` the QUEST is
        the shape of nearly every collision in the real key, and cost both
        entries their unambiguous credit before matching became type-aware."""
        g = golden(
            nodes=[
                gnode("Vallaki", entity_type="LOCATION"),
                gnode("Escort Ireena to Vallaki", entity_type="QUEST"),
            ]
        )

        assert ceiling(g)[0] == 1.0

    def test_an_ambiguous_endpoint_lowers_the_edge_ceiling(self):
        g = golden(
            nodes=[
                gnode("Vallaki", entity_type="LOCATION"),
                gnode("Vallaki Gates", entity_type="LOCATION"),
                gnode("Ireena Kolyana"),
            ],
            edges=[
                gedge("cos:npc:ireena kolyana", "cos:location:vallaki", "TRAVELED_TO"),
                gedge("cos:npc:ireena kolyana", "cos:npc:ireena kolyana", "KNOWS"),
            ],
        )

        assert ceiling(g)[1] == 0.5, "the edge through the ambiguous endpoint is uncreditable"

    def test_grade_reports_the_ceiling_alongside_the_score(self):
        g = golden(
            nodes=[
                gnode("Vallaki", entity_type="LOCATION"),
                gnode("Vallaki Gates", entity_type="LOCATION"),
            ]
        )
        report = grade([cnode("Vallaki", "LOCATION")], [], g)

        assert report.node_ceiling == 0.0
        assert report.edge_ceiling == 1.0
        assert report.node_recall_unambiguous <= report.node_ceiling

    def test_the_real_chapter_three_key_is_gradeable_to_its_own_ceiling(self):
        """A ceiling below 1.0 on the shipped key is a defect in the key. If this
        fails, fix the seed -- do not lower the bar."""
        import yaml

        from backend.canon.seed_loader import SEED_DIR, extractable_subset

        data = yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())

        for source in ("ch3", "ch1"):
            node_ceiling, edge_ceiling = ceiling(extractable_subset(data, source))
            assert node_ceiling == 1.0, f"{source} node ceiling is {node_ceiling}"
            assert edge_ceiling == 1.0, f"{source} edge ceiling is {edge_ceiling}"


class TestTypeAwareEdgeEndpoints:
    """An edge inherits the type rule through its endpoints: an endpoint name is
    typed by the candidate node that carries it, so an edge between wrongly typed
    (or never-extracted, therefore untyped) endpoints cannot be credited."""

    def test_edge_matches_when_both_endpoints_are_correctly_typed(self):
        g = golden(
            nodes=[gnode("Strahd von Zarovich"), gnode("Ireena Kolyana")],
            edges=[gedge("cos:npc:strahd von zarovich", "cos:npc:ireena kolyana", "SEEKS")],
        )
        report = grade(
            [cnode("Strahd", "NPC"), cnode("Ireena", "NPC")],
            [cedge("Strahd", "Ireena", "SEEKS")],
            g,
        )

        assert report.edge_recall == 1.0

    def test_edge_with_a_wrongly_typed_endpoint_is_not_credited(self):
        g = golden(
            nodes=[gnode("Strahd von Zarovich"), gnode("Ireena Kolyana")],
            edges=[gedge("cos:npc:strahd von zarovich", "cos:npc:ireena kolyana", "SEEKS")],
        )
        report = grade(
            [cnode("Strahd", "NPC"), cnode("Ireena", "LOCATION")],
            [cedge("Strahd", "Ireena", "SEEKS")],
            g,
        )

        assert report.edge_recall == 0.0
        assert report.edge_recall_unambiguous == 0.0

    def test_edge_whose_endpoint_was_never_extracted_as_a_node_is_not_credited(self):
        """The shotgun's 45,540 edges were emitted over bare name strings. An
        endpoint with no candidate node behind it has no type at all, and must
        not be credited on its name alone."""
        g = golden(
            nodes=[gnode("Strahd von Zarovich"), gnode("Ireena Kolyana")],
            edges=[gedge("cos:npc:strahd von zarovich", "cos:npc:ireena kolyana", "SEEKS")],
        )
        report = grade([], [cedge("Strahd", "Ireena", "SEEKS")], g)

        assert report.edge_recall == 0.0

    def test_a_quest_named_after_a_location_does_not_satisfy_the_locations_edge(self):
        g = golden(
            nodes=[gnode("Ismark Kolyanovich"), gnode("Vallaki", entity_type="LOCATION")],
            edges=[gedge("cos:npc:ismark kolyanovich", "cos:location:vallaki", "TRAVELED_TO")],
        )
        report = grade(
            [cnode("Ismark", "NPC"), cnode("Escort Ireena to Vallaki", "QUEST")],
            [cedge("Ismark", "Escort Ireena to Vallaki", "TRAVELED_TO")],
            g,
        )

        assert report.edge_recall == 0.0


class TestEdgeCollisions:
    def test_candidate_edge_matching_multiple_golden_edges_is_a_collision(self):
        """Two golden nodes sharing a token make one candidate edge satisfy both
        golden edges at once -- exactly the endpoint ambiguity that inflates
        node recall, but on the edge side."""
        g = golden(
            nodes=[gnode("Ireena Kolyana"), gnode("Ireena the Cursed"), gnode("Target")],
            edges=[
                gedge("cos:npc:ireena kolyana", "cos:npc:target", "SEEKS"),
                gedge("cos:npc:ireena the cursed", "cos:npc:target", "SEEKS"),
            ],
        )
        report = grade(
            [cnode("Ireena"), cnode("Target")], [cedge("Ireena", "Target", "SEEKS")], g
        )

        assert report.edge_collisions, "one candidate satisfying two golden edges must be flagged"

    def test_golden_edge_credited_via_ambiguous_endpoint_is_a_collision(self):
        """Only one golden edge here -- the ambiguity is that "Ireena" also
        names a second, unrelated golden NPC with no edge of its own. Same
        type, or matching would separate them and there would be no
        ambiguity to report."""
        g = golden(
            nodes=[gnode("Ireena"), gnode("Ireena the Cursed"), gnode("Target")],
            edges=[gedge("cos:npc:ireena", "cos:npc:target", "SEEKS")],
        )
        report = grade(
            [cnode("Ireena"), cnode("Target")], [cedge("Ireena", "Target", "SEEKS")], g
        )

        assert report.edge_collisions, "an ambiguous endpoint match must be surfaced"

    def test_unambiguous_edge_match_is_not_a_collision(self):
        g = golden(
            nodes=[gnode("A"), gnode("B")],
            edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
        )
        report = grade([cnode("A"), cnode("B")], [cedge("A", "B", "KNOWS")], g)

        assert report.edge_collisions == []


class TestUnambiguousEdgeRecall:
    def test_unambiguous_edge_match_counts(self):
        g = golden(
            nodes=[gnode("A"), gnode("B")],
            edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
        )
        report = grade([cnode("A"), cnode("B")], [cedge("A", "B", "KNOWS")], g)

        assert report.edge_recall_unambiguous == 1.0

    def test_ambiguous_endpoint_match_does_not_count_toward_unambiguous_recall(self):
        g = golden(
            nodes=[gnode("Ireena"), gnode("Ireena the Cursed"), gnode("Target")],
            edges=[gedge("cos:npc:ireena", "cos:npc:target", "SEEKS")],
        )
        report = grade(
            [cnode("Ireena"), cnode("Target")], [cedge("Ireena", "Target", "SEEKS")], g
        )

        assert report.edge_recall == 1.0
        assert report.edge_recall_unambiguous == 0.0
