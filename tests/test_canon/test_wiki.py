"""Parsing tests for the Forgotten Realms Wiki harvest.

No network. Fixtures under `fixtures/wiki/` are verbatim MediaWiki API responses saved
once by hand; the wiki text they contain is CC-BY-SA content of the Forgotten Realms
Wiki (forgottenrealms.fandom.com).
"""

import json
from pathlib import Path

import pytest

from backend.canon import wiki
from backend.graph.schema import CANON_ENTITY_TYPES, EntityType

FIXTURES = Path(__file__).parent / "fixtures" / "wiki"


@pytest.fixture(scope="module")
def index_wikitext() -> str:
    payload = json.loads((FIXTURES / "index-parse.json").read_text())
    return payload["parse"]["wikitext"]


@pytest.fixture(scope="module")
def pages() -> dict[str, wiki.WikiPage]:
    payload = json.loads((FIXTURES / "pages-batch.json").read_text())
    return wiki.parse_pages_response(payload)


# --------------------------------------------------------------------------- splitting


def test_split_top_level_keeps_nested_link_pipes_intact():
    """The trap from the brief: a naive split('|') shreds `[[A|B]]` inside a value."""
    raw = "| home = [[Barovia (vilage)|Barovia]], [[Domains of Dread]]"

    assert wiki.split_top_level(raw) == [
        "",
        " home = [[Barovia (vilage)|Barovia]], [[Domains of Dread]]",
    ]


def test_split_top_level_splits_template_params_but_not_nested_templates():
    raw = 'name = X|basicrefs = <ref>{{Cite book/Curse of Strahd|45-46}}</ref>|home = [[A|B]]'

    assert wiki.split_top_level(raw) == [
        "name = X",
        "basicrefs = <ref>{{Cite book/Curse of Strahd|45-46}}</ref>",
        "home = [[A|B]]",
    ]


def test_split_top_level_splits_commas_outside_links():
    raw = "[[Barovia (vilage)|Barovia, the village]], [[Domains of Dread]]"

    assert wiki.split_top_level(raw, ",") == [
        "[[Barovia (vilage)|Barovia, the village]]",
        " [[Domains of Dread]]",
    ]


# ---------------------------------------------------------------------------- markup


def test_strip_markup_keeps_display_form_and_drops_refs():
    raw = "[[Barovia (vilage)|Barovia]]<ref name=\"CoS-p45-46\">{{Cite book/x|45}}</ref>"

    assert wiki.strip_markup(raw) == "Barovia"


def test_strip_markup_keeps_bare_link_target():
    assert wiki.strip_markup("''[[Tome of Strahd]]''") == "Tome of Strahd"


def test_split_values_handles_commas_line_breaks_and_duplicates():
    raw = "[[Barovia (vilage)|Barovia]], [[Barovia]]<br/>[[Domains of Dread]]"

    assert wiki.split_values(raw) == ["Barovia", "Domains of Dread"]


def test_split_values_of_empty_field_is_empty():
    assert wiki.split_values("   ") == []


# ----------------------------------------------------------------------------- index


def test_parse_index_finds_every_indexed_entity(index_wikitext):
    assert len(wiki.parse_index(index_wikitext)) == 677


def test_parse_index_maps_each_subsection_to_its_entity_type(index_wikitext):
    entries = wiki.parse_index(index_wikitext)
    by_category: dict[str, set[EntityType]] = {}
    counts: dict[str, int] = {}
    for entry in entries:
        by_category.setdefault(entry.category, set()).add(entry.entity_type)
        counts[entry.category] = counts.get(entry.category, 0) + 1

    assert by_category == {
        "Characters": {EntityType.NPC},
        "Creatures": {EntityType.MONSTER},
        "Items": {EntityType.ITEM},
        "Magic": {EntityType.ITEM},
        "Locations": {EntityType.LOCATION},
        "Organizations": {EntityType.FACTION},
        "Miscellaneous": {EntityType.LORE},
    }
    assert counts == {
        "Characters": 197,
        "Creatures": 87,
        "Items": 148,
        "Magic": 167,
        "Locations": 38,
        "Organizations": 12,
        "Miscellaneous": 28,
    }


def test_parse_index_ignores_subsections_that_are_not_entity_categories(index_wikitext):
    """`===Trivia===` and friends sit inside the same section and index nothing."""
    categories = {e.category for e in wiki.parse_index(index_wikitext)}

    assert "Trivia" not in categories
    assert "Connections" not in categories
    assert categories <= set(wiki.INDEX_SECTION_TYPES)


def test_parse_index_skips_a_subsection_with_no_entity_type():
    """A heading nobody has mapped indexes nothing, rather than defaulting to a type."""
    wikitext = (
        "==Index==\n"
        "===Characters===\n"
        "{{Index\n|index = {{P|[[Ismark Kolyanovich]]|43}}\n}}\n"
        "===Trivia===\n"
        "{{Index\n|index = {{P|[[Ravenloft (module)]]|9}}\n}}\n"
    )

    entries = wiki.parse_index(wikitext)

    assert [(e.target, e.category) for e in entries] == [("Ismark Kolyanovich", "Characters")]


def test_index_section_types_are_all_canon_entity_types():
    assert set(wiki.INDEX_SECTION_TYPES.values()) <= CANON_ENTITY_TYPES


def test_parse_index_keeps_target_as_name_and_display_as_alias(index_wikitext):
    by_target = {e.target: e for e in wiki.parse_index(index_wikitext)}

    assert by_target["Wererabbit"].display == "werehare"
    assert by_target["Wererabbit"].entity_type is EntityType.MONSTER
    # Unpiped entries have no separate display form to record.
    assert by_target["Ireena Kolyana"].display is None


def test_parse_index_records_the_book_pages_cited_by_the_index(index_wikitext):
    by_target = {e.target: e for e in wiki.parse_index(index_wikitext)}

    assert by_target["Arik Lorensk"].index_pages == "43-44"
    assert by_target["Blood of the Vine"].index_pages == "178"


def test_parse_index_records_the_subcategory_heading(index_wikitext):
    by_target = {e.target: e for e in wiki.parse_index(index_wikitext)}

    assert by_target["Blood of the Vine"].subcategory == "Building & Sites"
    assert by_target["Arik Lorensk"].subcategory is None


# --------------------------------------------------------------------------- infobox


def test_parse_infobox_reads_the_lead_template_of_a_real_page(pages):
    box = pages["Arik Lorensk"].infobox

    assert box["name"] == "Arik Lorensk"
    assert box["occupation"] == "Barkeeper"
    assert box["race"] == "[[Human]]"


def test_parse_infobox_preserves_the_wikis_own_typo(pages):
    """`[[Barovia (vilage)|Barovia]]` is misspelt on the wiki. Record, do not correct."""
    assert "Barovia (vilage)" in pages["Arik Lorensk"].infobox["home"]


def test_parse_infobox_returns_empty_string_for_an_empty_field(pages):
    box = pages["Arik Lorensk"].infobox

    assert box["aliases"] == ""
    assert box["spouses"] == ""


def test_parse_infobox_ignores_maintenance_templates_above_the_infobox(pages):
    """Wererabbit's page opens with `{{Otheruses…}}`; the infobox is the one after it."""
    assert pages["Wererabbit"].infobox["name"] == "Wererabbit"


def test_parse_infobox_finds_nothing_on_a_page_that_has_no_infobox(pages):
    """Carousel has no infobox, only an `{{Appearances}}` block far below the lead.

    An infobox is lead content; a template further down that happens to have several
    named parameters is not one, and inventing fields from it would be fabrication.
    """
    assert pages["carousel"].exists is True
    assert pages["carousel"].infobox == {}


def test_parse_pages_response_is_keyed_by_the_requested_title(pages):
    """MediaWiki capitalises `carousel` to `Carousel`; the index spells it lowercase."""
    assert "carousel" in pages
    assert pages["carousel"].title == "Carousel"


def test_parse_cited_pages_pulls_curse_of_strahd_citations(pages):
    box = pages["Arik Lorensk"].infobox

    assert wiki.parse_cited_pages(box["basicrefs"]) == ["45-46"]


def test_parse_cited_pages_ignores_citations_of_other_books():
    raw = "<ref>{{Cite book/Monster Manual 5th edition|345}}</ref>"

    assert wiki.parse_cited_pages(raw) == []


# ----------------------------------------------------------------------------- pages


def test_parse_pages_response_marks_a_redlink_as_absent(pages):
    """Ireena Kolyana is indexed by the book but has no Forgotten Realms Wiki page."""
    assert pages["Ireena Kolyana"].exists is False
    assert pages["Ireena Kolyana"].infobox == {}


def test_parse_pages_response_records_a_redirect_without_following_it(pages):
    assert pages["Spectre"].exists is True
    assert pages["Spectre"].redirect_to == "Specter"
    assert pages["Spectre"].infobox == {}


# -------------------------------------------------------------------------- document


def _document(index_wikitext, pages):
    return wiki.build_document(wiki.parse_index(index_wikitext), pages, fetch_date="2026-08-11")


def test_build_document_records_provenance_and_licence(index_wikitext, pages):
    source = _document(index_wikitext, pages)["source"]

    assert source["api_url"] == wiki.API_URL
    assert source["licence"] == "CC-BY-SA"
    assert source["fetched"] == "2026-08-11"


def test_build_document_takes_the_fetch_date_from_the_caller(index_wikitext, pages):
    assert _document(index_wikitext, pages)["source"]["fetched"] != ""
    other = wiki.build_document(wiki.parse_index(index_wikitext), pages, fetch_date="1999-01-01")
    assert other["source"]["fetched"] == "1999-01-01"


def test_build_document_carries_index_display_forms_into_aliases(index_wikitext, pages):
    entries = {e["name"]: e for e in _document(index_wikitext, pages)["entries"]}

    assert entries["Wererabbit"]["aliases"] == ["werehare"]


def test_build_document_records_infobox_aliases(index_wikitext, pages):
    entries = {e["name"]: e for e in _document(index_wikitext, pages)["entries"]}

    assert "Blood on the Vine" in entries["Blood of the Vine"]["aliases"]


def test_build_document_marks_entities_the_batch_did_not_cover_as_unfetched(
    index_wikitext, pages
):
    entries = {e["name"]: e for e in _document(index_wikitext, pages)["entries"]}

    assert entries["Arik Lorensk"]["fetched"] is True
    assert entries["Arik Lorensk"]["page_exists"] is True
    # Indexed, fetched, and genuinely absent from the wiki -- a redlink.
    assert entries["Ireena Kolyana"]["fetched"] is True
    assert entries["Ireena Kolyana"]["page_exists"] is False
    # Not in this batch at all: unknown, which is not the same claim as "no page".
    assert entries["Strahd von Zarovich"]["fetched"] is False
    assert entries["Strahd von Zarovich"]["page_exists"] is False


def test_build_document_joins_a_page_whose_title_the_wiki_capitalised(index_wikitext, pages):
    entries = {e["name"]: e for e in _document(index_wikitext, pages)["entries"]}

    assert entries["carousel"]["fetched"] is True
    assert entries["carousel"]["aliases"] == ["merry-go-round"]


def test_build_document_splits_multi_valued_fields(index_wikitext, pages):
    entries = {e["name"]: e for e in _document(index_wikitext, pages)["entries"]}

    assert entries["Arik Lorensk"]["fields"]["home"] == ["Barovia", "Domains of Dread"]
    assert entries["Arik Lorensk"]["fields"]["race"] == ["Human"]
    assert entries["Arik Lorensk"]["fields"]["occupation"] == "Barkeeper"


def test_build_document_omits_empty_fields(index_wikitext, pages):
    entries = {e["name"]: e for e in _document(index_wikitext, pages)["entries"]}

    assert "spouses" not in entries["Arik Lorensk"]["fields"]


def test_build_document_carries_the_cited_book_pages(index_wikitext, pages):
    entries = {e["name"]: e for e in _document(index_wikitext, pages)["entries"]}

    assert entries["Arik Lorensk"]["cited_pages"] == ["45-46"]
    assert entries["Arik Lorensk"]["index_pages"] == "43-44"
