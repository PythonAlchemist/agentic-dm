"""Lookup tests for the canon gazetteer. No network."""

import json

import pytest

from backend.canon.gazetteer import Gazetteer, GazetteerEntry, load_gazetteer


def entry(name: str, **kw) -> GazetteerEntry:
    kw.setdefault("entity_type", "NPC")
    kw.setdefault("wiki_category", "Characters")
    return GazetteerEntry(name=name, **kw)


@pytest.fixture
def gaz() -> Gazetteer:
    return Gazetteer(
        [
            entry(
                "Ireena Kolyana",
                aliases=("Ireena Kolyanovich",),
                fields={"home": ["Barovia"], "parents": ["Kolyan Indirovich"]},
            ),
            entry("Strahd von Zarovich", aliases=("Strahd I",), fields={"home": ["Ravenloft"]}),
            entry("Barovia", entity_type="LOCATION", wiki_category="Locations"),
            entry(
                "Blood of the Vine",
                entity_type="LOCATION",
                wiki_category="Locations",
                aliases=("Blood on the Vine", "Blood O' the Vine"),
            ),
        ]
    )


# ---------------------------------------------------------------------------- matching


def test_lookup_matches_exactly(gaz):
    assert gaz.lookup("Ireena Kolyana").name == "Ireena Kolyana"


def test_lookup_matches_case_insensitively(gaz):
    assert gaz.lookup("ireena kolyana").name == "Ireena Kolyana"
    assert gaz.lookup("  STRAHD VON ZAROVICH ").name == "Strahd von Zarovich"


def test_lookup_matches_a_recorded_alias(gaz):
    assert gaz.lookup("Blood on the Vine").name == "Blood of the Vine"
    assert gaz.lookup("strahd i").name == "Strahd von Zarovich"


def test_lookup_does_not_match_a_token_subset(gaz):
    """The bug that let a regex shotgun outscore the pipeline. `Ireena` is not an entry."""
    assert gaz.lookup("Ireena") is None
    assert gaz.lookup("Kolyana") is None
    assert gaz.lookup("Strahd") is None


def test_lookup_does_not_match_a_superstring(gaz):
    assert gaz.lookup("Escort Ireena Kolyana to Vallaki") is None
    assert gaz.lookup("Barovia village") is None


def test_lookup_does_not_match_a_near_miss_spelling(gaz):
    """No fuzzy fallback: a one-character transcription defect stays unknown."""
    assert gaz.lookup("Ireena Kolyanna") is None
    assert gaz.lookup("Blood of the Vines") is None


def test_lookup_prefers_an_exact_name_over_another_entrys_alias():
    gaz = Gazetteer(
        [
            entry("Blood on the Vine", entity_type="LOCATION", wiki_category="Locations"),
            entry(
                "Blood of the Vine",
                entity_type="ITEM",
                wiki_category="Items",
                aliases=("Blood on the Vine",),
            ),
        ]
    )

    assert gaz.lookup("Blood on the Vine").entity_type == "LOCATION"


def test_unknown_name_is_not_known(gaz):
    assert gaz.is_known("skeleton") is False
    assert gaz.is_known("K20") is False
    assert gaz.is_known("Barovia") is True


def test_entity_type_returns_the_indexed_type(gaz):
    assert gaz.entity_type("Barovia") == "LOCATION"
    assert gaz.entity_type("ireena kolyana") == "NPC"
    assert gaz.entity_type("secret door") is None


# --------------------------------------------------------------------------- relations


def test_relations_projects_home_onto_located_in(gaz):
    assert ("Ireena Kolyana", "LOCATED_IN", "Barovia") in gaz.relations("Ireena Kolyana")


def test_relations_projects_kinship_onto_related_to(gaz):
    assert ("Ireena Kolyana", "RELATED_TO", "Kolyan Indirovich") in gaz.relations("Ireena Kolyana")


def test_relations_of_an_unknown_name_is_empty(gaz):
    assert gaz.relations("skeleton") == []


def test_relations_uses_the_canonical_name_of_the_matched_entry(gaz):
    assert all(s == "Ireena Kolyana" for s, _, _ in gaz.relations("ireena kolyana"))


# ------------------------------------------------------------------------------ load


def test_load_gazetteer_reads_a_harvested_document(tmp_path):
    doc = {
        "source": {"api_url": "https://example.invalid/api.php", "licence": "CC-BY-SA"},
        "entries": [
            {
                "name": "Arik Lorensk",
                "aliases": [],
                "entity_type": "NPC",
                "wiki_category": "Characters",
                "page_exists": True,
                "index_pages": "43-44",
                "cited_pages": ["45-46"],
                "fields": {"occupation": "Barkeeper", "home": ["Barovia"]},
            }
        ],
    }
    path = tmp_path / "curse-of-strahd.json"
    path.write_text(json.dumps(doc))

    loaded = load_gazetteer(path)

    assert len(loaded) == 1
    assert loaded.lookup("Arik Lorensk").cited_pages == ("45-46",)
    assert loaded.relations("Arik Lorensk") == [("Arik Lorensk", "LOCATED_IN", "Barovia")]
    assert loaded.source["licence"] == "CC-BY-SA"
