"""The hand-authored half of the location hierarchy.

REGION, SETTLEMENT and WILD cannot be derived from anything the document says
about itself -- no key distinguishes a village from a wood -- so they are
authored, in a YAML that lives beside the canon seed because a seed is source:
committed, reviewed, and diffable. Roughly fifteen entries for the whole book.

Nothing here infers a subtype from a name substring. "Village of" works on
Barovia and breaks on the next book, and a wrong label is worse than no label
because it is indistinguishable from a checked one.
"""

import pytest
import yaml

from backend.canon.assembler import slugify
from backend.canon.seed_loader import (
    LOCATION_SUBTYPE_SEED,
    load_location_subtypes,
    validate_location_subtypes,
)
from backend.graph.schema import LocationSubtype

DERIVABLE = {LocationSubtype.SITE, LocationSubtype.AREA}


@pytest.fixture
def authored():
    return yaml.safe_load(LOCATION_SUBTYPE_SEED.read_text())


class TestSeedIntegrity:
    def test_the_seed_exists(self):
        assert LOCATION_SUBTYPE_SEED.exists()

    def test_it_validates(self, authored):
        assert validate_location_subtypes(authored) == []

    def test_it_authors_only_what_cannot_be_derived(self, authored):
        """A hand-authored SITE or AREA would be a human guessing at something
        the key convention already answers, and the key has never been wrong."""
        for entry in authored["locations"]:
            assert LocationSubtype(entry["subtype"]) not in DERIVABLE, entry

    def test_it_covers_the_three_loaded_chapters(self):
        subtypes = load_location_subtypes()
        expected = {
            "barovia": LocationSubtype.REGION,
            "vallaki": LocationSubtype.SETTLEMENT,
            "krezk": LocationSubtype.SETTLEMENT,
            "the-village-of-barovia": LocationSubtype.SETTLEMENT,
            "svalich-woods": LocationSubtype.WILD,
            "old-svalich-road": LocationSubtype.WILD,
            "tsolenka-pass": LocationSubtype.WILD,
            "yester-hill": LocationSubtype.WILD,
        }
        assert expected.items() <= subtypes.items()

    def test_it_is_keyed_on_the_slug(self, authored):
        """Matched the way `mint_id` mints, so two spellings of one name are one
        entry -- `Bildrath's` and `Bildrath’s` differ by one invisible character."""
        subtypes = load_location_subtypes()
        for entry in authored["locations"]:
            assert slugify(entry["name"]) in subtypes, entry

    def test_aliases_reach_the_same_subtype(self, authored):
        """The extractor's spelling and the chapter title's need not agree, and
        listing both by hand is authorship rather than a fuzzy match."""
        subtypes = load_location_subtypes()
        for entry in authored["locations"]:
            for alias in entry.get("aliases", []):
                assert subtypes[slugify(alias)] == LocationSubtype(entry["subtype"])


class TestValidation:
    def test_an_unknown_subtype_is_reported(self):
        """`WILDS` (typo) must not load silently: an unrecognised rung would
        confer no label and the place would look deliberately unclassified."""
        problems = validate_location_subtypes(
            {"locations": [{"name": "Svalich Woods", "subtype": "WILDS"}]}
        )

        assert any("WILDS" in p for p in problems)

    def test_a_missing_name_is_reported(self):
        problems = validate_location_subtypes({"locations": [{"subtype": "WILD"}]})

        assert any("name" in p for p in problems)

    def test_a_name_that_slugifies_to_nothing_is_reported(self):
        problems = validate_location_subtypes({"locations": [{"name": "!!", "subtype": "WILD"}]})

        assert any("!!" in p for p in problems)

    def test_two_entries_claiming_one_slug_are_reported(self):
        """Two rungs for one place is a contradiction, and last-wins would hide
        it behind a silent dict overwrite."""
        problems = validate_location_subtypes(
            {
                "locations": [
                    {"name": "Barovia", "subtype": "REGION"},
                    {"name": "Barovia", "subtype": "SETTLEMENT"},
                ]
            }
        )

        assert any("barovia" in p for p in problems)

    def test_an_alias_colliding_with_another_entry_is_reported(self):
        problems = validate_location_subtypes(
            {
                "locations": [
                    {"name": "Barovia", "subtype": "REGION"},
                    {"name": "Vallaki", "aliases": ["Barovia"], "subtype": "SETTLEMENT"},
                ]
            }
        )

        assert any("barovia" in p for p in problems)

    def test_loading_an_invalid_seed_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.safe_dump({"locations": [{"name": "X", "subtype": "NOPE"}]}))

        with pytest.raises(ValueError, match="NOPE"):
            load_location_subtypes(path)
