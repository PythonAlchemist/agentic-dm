"""Scoring candidates against the golden set.

Recall is computable; precision is not. The golden set lists 18 nodes for
chapter 3, but the chapter contains far more nameable things, so an unmatched
candidate is usually a legitimate entity the key omits. Scoring precision here
would punish an extractor for being thorough.
"""

from backend.canon.grade import grade, normalize_name
from backend.canon.models import CandidateEdge, CandidateNode


def golden(nodes=None, edges=None) -> dict:
    return {"nodes": nodes or [], "edges": edges or []}


def gnode(name, entity_type="NPC", **kw):
    return {"id": f"cos:npc:{name.lower()}", "name": name, "entity_type": entity_type, **kw}


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
        report = grade([], [cedge("A", "B", "KNOWS")], g)

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
