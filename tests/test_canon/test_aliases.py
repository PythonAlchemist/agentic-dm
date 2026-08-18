"""Aliases, without a database.

The normalisation is three operations and the whole point of the file is that it
is only ever three. Most of what follows is therefore a test that something did
NOT happen -- no distance, no prefix, no token subset -- because the failures
this module exists to prevent all look like a helpful extra rule.
"""

import pytest

from backend.canon.aliases import WriteAlias, normalize, plan_aliases
from backend.canon.seed_loader import (
    LOCATION_SUBTYPE_SEED,
    load_aliases,
    validate_aliases,
)


def _every_form() -> set[str]:
    """Every authored surface form in the committed seed, case-folded.

    Folded because these are refusal tests: recording `Castle` rather than
    `castle` must fail them too, and an exact-string check would quietly let
    the capitalised spelling back in.
    """
    return {a.lower() for forms in load_aliases().values() for a in forms}


class TestNormalize:
    def test_it_lowercases(self):
        assert normalize("Strahd von Zarovich") == "strahd von zarovich"

    def test_it_trims(self):
        assert normalize("  Strahd  ") == "strahd"

    def test_it_folds_the_curly_apostrophe(self):
        assert normalize("Bildrath’s Mercantile") == "bildrath's mercantile"

    def test_the_two_apostrophes_normalize_alike(self):
        """The one thing the folding is for: the book sets U+2019 and the
        extractor emits ASCII, and they are the same name."""
        assert normalize("Bildrath’s Mercantile") == normalize("Bildrath's Mercantile")

    def test_it_does_not_strip_punctuation(self):
        """A slug would drop the colon and the comma. `normalized` is not a
        slug: it keeps every character the book wrote except the two that are
        genuinely typographic, so two titles differing only by punctuation stay
        two names."""
        assert normalize("The Blade of Truth: The Uses of Logic") == (
            "the blade of truth: the uses of logic"
        )

    def test_it_does_not_collapse_internal_whitespace(self):
        assert normalize("Mad  Mary") == "mad  mary"

    def test_it_does_not_strip_a_leading_article(self):
        """`The Village of Barovia` and `Village of Barovia` are two surface
        forms and are recorded as two. Folding them here would be a rule, and a
        rule would also merge `The Blade of Truth` with `Blade of Truth`."""
        assert normalize("The Village of Barovia") != normalize("Village of Barovia")

    def test_a_prefix_is_not_the_same_name(self):
        """THE ENTIRE POINT. `Strahd` reaches `Strahd von Zarovich` because a
        human wrote it down, never because one is a prefix of the other."""
        assert normalize("Strahd") != normalize("Strahd von Zarovich")

    def test_a_token_subset_is_not_the_same_name(self):
        """The specific loose match that let a candidate `Ireena` credit the
        quest `Escort Ireena to Vallaki`, and so let a ten-line regex outscore a
        real extractor."""
        assert normalize("Ireena") != normalize("Escort Ireena to Vallaki")


class TestPlanAliases:
    def test_an_entity_is_always_an_alias_of_its_own_name(self):
        """The invariant lookup rests on. Without it, resolving a name is two
        traversals -- the node's `name` and its aliases -- which is two paths
        free to disagree."""
        assert plan_aliases([("cos:donavich", "Donavich")]) == [
            WriteAlias("cos:donavich", "Donavich")
        ]

    def test_an_authored_spelling_is_added_beside_the_canonical_one(self):
        planned = plan_aliases(
            [("cos:strahd-von-zarovich", "Strahd von Zarovich")],
            {"strahd-von-zarovich": ("Strahd von Zarovich", "Strahd")},
        )
        assert [a.name for a in planned] == ["Strahd", "Strahd von Zarovich"]

    def test_an_entry_is_found_by_the_slug_of_any_spelling_in_it(self):
        """The node is minted under whichever spelling won the provenance
        tiebreak, so the seed must reach it from either."""
        authored = {
            "the-village-of-barovia": ("The Village of Barovia", "Village of Barovia"),
            "village-of-barovia": ("The Village of Barovia", "Village of Barovia"),
        }
        for minted in ("The Village of Barovia", "Village of Barovia"):
            planned = plan_aliases([("cos:village", minted)], authored)
            assert {a.name for a in planned} == {
                "The Village of Barovia",
                "Village of Barovia",
            }

    def test_a_curly_name_picks_up_an_entry_keyed_on_the_straight_one(self):
        """Slug matching is what lets the seed carry one spelling of a
        possessive rather than every typographic variant of it."""
        planned = plan_aliases(
            [("cos:e1", "Bildrath’s Mercantile")],
            {"bildrath-s-mercantile": ("Bildrath's Mercantile",)},
        )
        assert {a.name for a in planned} == {
            "Bildrath’s Mercantile",
            "Bildrath's Mercantile",
        }

    def test_two_spellings_that_normalize_alike_stay_two_aliases(self):
        """They are two SURFACE FORMS. Collapsing them would leave the graph
        unable to say which one a section actually set."""
        planned = plan_aliases(
            [("cos:e1", "Bildrath’s Mercantile")],
            {"bildrath-s-mercantile": ("Bildrath's Mercantile",)},
        )
        assert len({a.name for a in planned}) == 2
        assert len({a.normalized for a in planned}) == 1

    def test_the_canonical_name_is_not_duplicated_when_the_seed_repeats_it(self):
        planned = plan_aliases(
            [("cos:krezk", "Krezk")], {"krezk": ("Krezk", "Village of Krezk")}
        )
        assert [a.name for a in planned] == ["Krezk", "Village of Krezk"]

    def test_a_blank_spelling_never_becomes_a_node(self):
        """`mention_pattern` refuses to compile one, so an `:Alias` for it could
        never be matched and no lookup could resolve it."""
        planned = plan_aliases([("cos:e1", "Church")], {"church": ("Church", "   ")})
        assert [a.name for a in planned] == ["Church"]

    def test_an_entity_with_no_entry_is_untouched_by_someone_elses(self):
        planned = plan_aliases(
            [("cos:doru", "Doru")],
            {"strahd-von-zarovich": ("Strahd von Zarovich", "Strahd")},
        )
        assert [a.name for a in planned] == ["Doru"]

    def test_the_order_is_determined_by_the_data_not_the_dict(self):
        forward = plan_aliases(
            [("cos:b", "Doru"), ("cos:a", "Donavich")],
            {"doru": ("Doru", "Doru the Spawn")},
        )
        backward = plan_aliases(
            [("cos:a", "Donavich"), ("cos:b", "Doru")],
            {"doru": ("Doru", "Doru the Spawn")},
        )
        assert forward == backward

    def test_the_normalized_property_is_the_module_rule_and_not_a_second_one(self):
        assert WriteAlias("cos:e", " Bildrath’s ").normalized == "bildrath's"
        assert WriteAlias("cos:e", "X").properties == {
            "normalized": "x",
            # The graph-wide caption. On an :Alias it restates the merge key,
            # which is the one node kind where that is redundant -- written
            # anyway so the Browser rule has no exceptions.
            "display_name": "X",
        }


class TestTheSeed:
    def test_the_authored_seed_loads_and_reaches_strahd(self):
        authored = load_aliases()
        assert "Strahd" in authored["strahd-von-zarovich"]

    def test_every_authored_entry_is_reachable_from_each_of_its_spellings(self):
        from backend.canon.assembler import slugify

        authored = load_aliases()
        for slug, forms in authored.items():
            assert slug in {slugify(f) for f in forms}

    def test_barovia_alone_is_deliberately_not_an_alias_of_the_village(self):
        """The region and the settlement share a word and are different places.
        An alias would merge thirteen mentions of the valley into the village."""
        authored = load_aliases()
        assert "Barovia" not in authored.get("the-village-of-barovia", ())

    def test_mary_alone_is_deliberately_not_an_alias_of_mad_mary(self):
        """The foreword's Mary is Mary Shelley. This is the bar an entry has to
        clear, and it is one line away in every direction."""
        authored = load_aliases()
        assert "Mary" not in authored.get("mad-mary", ())

    def test_the_short_forms_that_survived_the_corpus_check_are_recorded(self):
        """Counted standalone across every chapter, not just the one that
        prompted them."""
        authored = load_aliases()
        assert "Bildrath" in authored.get("bildrath-cantemir", ())
        assert "Arik" in authored.get("arik-lorensk", ())
        assert "Kolyan" in authored.get("kolyan-indirovich", ())

    def test_lucian_alone_belongs_to_a_priest_in_another_town(self):
        """15 standalone occurrences, nearly all Father Lucian Petrovich of
        Vallaki. The alias would move a priest's whole life onto a
        seven-year-old boy from Barovia."""
        authored = load_aliases()
        assert "Lucian" not in authored.get("lucian-jarov", ())

    def test_blinsky_alone_is_a_brand_stamped_on_toys(self):
        """31 standalone, mostly `Blinsky toy` -- an object, not the toymaker."""
        authored = load_aliases()
        assert "Blinsky" not in authored.get("gadof-blinsky", ())


class TestSeedValidation:
    def test_an_entry_with_no_spellings_is_refused(self):
        problems = validate_aliases({"aliases": [{"name": "Strahd von Zarovich"}]})
        assert any("records no spellings" in p for p in problems)

    def test_an_unnameable_spelling_is_refused(self):
        """It could never become a node, and the spelling it was meant to record
        would read exactly like one nobody authored."""
        problems = validate_aliases(
            {"aliases": [{"name": "Strahd von Zarovich", "aliases": ["!!!"]}]}
        )
        assert any("slugifies to nothing" in p for p in problems)

    def test_two_entries_disagreeing_about_one_slug_are_refused(self):
        """A dict would resolve this by keeping whichever the author wrote
        last, silently."""
        problems = validate_aliases(
            {
                "aliases": [
                    {"name": "Ismark Kolyanovich", "aliases": ["Ismark"]},
                    {"name": "Ismark Kolyanovich", "aliases": ["Ismark the Lesser"]},
                ]
            }
        )
        assert any("claimed by two alias entries" in p for p in problems)

    def test_two_entries_agreeing_are_not_a_problem(self):
        entry = {"name": "Ismark Kolyanovich", "aliases": ["Ismark"]}
        assert validate_aliases({"aliases": [entry, dict(entry)]}) == []

    def test_the_committed_seed_validates(self):
        import yaml

        data = yaml.safe_load(LOCATION_SUBTYPE_SEED.read_text())
        assert validate_aliases(data) == []

    def test_an_invalid_seed_raises_rather_than_loading_half_of_it(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("aliases:\n  - name: Strahd\n    aliases: []\n")
        with pytest.raises(ValueError, match="invalid alias seed"):
            load_aliases(bad)

    def test_the_correct_shorthands_are_withdrawn_on_measurement(self):
        """`castle`, `abbey`, `temple` and `winery` all PASSED the corpus check
        -- every occurrence refers to the intended place -- and are still not
        recorded, because retrieval measured worse with them: 67% -> 65%, and
        "what guards the madhouse at the abbey" went from a hit to a miss.

        `abbey` pulls the whole Abbey of Saint Markovia into the anchor set and
        the madhouse loses to its own siblings. Being right about the book is
        not sufficient; a broad anchor drowns a specific answer while ranking
        cannot separate them.
        """
        assert not ({"castle", "abbey", "temple", "winery"} & _every_form())

    def test_windmill_is_heraldry_in_death_house(self):
        """25 occurrences, 7 of them in Death House: a coat of arms, a cameo
        worked into a sword hilt, a framed picture. Not Old Bonegrinder --
        the same shape as `Blinsky toy`."""
        forms = {a.lower() for a in load_aliases().get("old-bonegrinder", ())}
        assert "windmill" not in forms

    def test_the_ambiguous_shorthands_are_refused(self):
        """Barovia and Vallaki each have a church, a burgomaster and a mansion.
        `count` is also an English verb."""
        assert not ({"church", "mansion", "burgomaster", "tavern",
                     "town", "village", "count", "devil"} & _every_form())
