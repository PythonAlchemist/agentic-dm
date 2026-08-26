"""Which nodes are one place minted twice, and which are two places.

Pure and exact: `plan_merges` takes dicts and returns a plan, so the rule that
decides whether `Kitchen` is six rooms or one can be stated as a test rather
than inferred from a graph afterwards.
"""

from backend.canon.books import BookScheme
from backend.canon.duplicates import (
    Merge,
    is_area_keyed,
    is_keyed,
    normalize,
    plan_globals,
    plan_merges,
)


def entity(entity_id: str, name: str) -> dict:
    return {"id": entity_id, "name": name}


class TestWhatCountsAsTheSameName:
    def test_a_leading_article_is_not_part_of_the_name(self):
        assert normalize("The Amber Temple") == normalize("Amber Temple")

    def test_case_is_not_either(self):
        assert normalize("shrine of Mother Night") == normalize("Shrine of Mother Night")

    def test_an_article_inside_the_name_is_left_alone(self):
        """`Order of the Silver Dragon` keeps its middle `the`; only a LEADING
        article is a grammatical wrapper rather than part of the name."""
        assert normalize("Order of the Silver Dragon") == "order of the silver dragon"

    def test_a_keyed_id_is_the_books_own_area_numbering(self):
        assert is_keyed("cos:castle-ravenloft:k65-kitchen")
        assert not is_keyed("cos:svalich-woods")


class TestRoomsThatShareANameAreNotDuplicates:
    """The case `mint_id` keys places to prevent. Merging these would collapse
    six rooms into one and silently delete the CONTAINS edges of five."""

    def test_six_kitchens_in_four_buildings_stay_six(self):
        kitchens = [
            entity("cos:the-town-of-vallaki:n2e-kitchen", "Kitchen"),
            entity("cos:the-town-of-vallaki:n3g-kitchen", "Kitchen"),
            entity("cos:argynvostholt:q10-kitchen", "Kitchen"),
            entity("cos:castle-ravenloft:k65-kitchen", "Kitchen"),
        ]
        assert plan_merges(kitchens) == []

    def test_two_chapels_in_two_chapters_stay_two(self):
        assert plan_merges([
            entity("cos:castle-ravenloft:k15-chapel", "Chapel"),
            entity("cos:the-village-of-barovia:e5f-chapel", "Chapel"),
        ]) == []


class TestAPlaceAndItsOwnAreaEntry:
    """Sixteen of these, every one read by hand before the rule was written."""

    def test_the_unkeyed_node_survives(self):
        """Its id says what the thing IS. The keyed id says which chapter got
        to it first, which is real but is not identity."""
        [merge] = plan_merges([
            entity("cos:svalich-woods", "Svalich Woods"),
            entity("cos:the-lands-of-barovia:c-svalich-woods", "Svalich Woods"),
        ])
        assert merge.survivor == "cos:svalich-woods"
        assert merge.losers == ("cos:the-lands-of-barovia:c-svalich-woods",)

    def test_the_article_is_dropped_from_the_kept_name(self):
        [merge] = plan_merges([
            entity("cos:the-village-of-barovia", "The Village of Barovia"),
            entity("cos:the-lands-of-barovia:e-village-of-barovia", "Village of Barovia"),
        ])
        assert merge.survivor_name == "Village of Barovia"
        # The old spelling has to keep resolving -- a DM who types it, and every
        # `note_named` scan already recorded under it, must still land here.
        assert "The Village of Barovia" in merge.aliases

    def test_the_lowercase_spelling_is_not_the_one_kept(self):
        [merge] = plan_merges([
            entity("cos:shrine-of-mother-night", "shrine of Mother Night"),
            entity("cos:werewolf-den:z7-shrine-of-mother-night", "Shrine of Mother Night"),
        ])
        assert merge.survivor_name == "Shrine of Mother Night"

    def test_a_place_keyed_in_two_chapters_folds_into_the_one_unkeyed_node(self):
        """Krezk is headed as an area by the Lands overview AND by its own
        chapter. Three nodes, one village."""
        [merge] = plan_merges([
            entity("cos:the-village-of-krezk", "The Village of Krezk"),
            entity("cos:the-lands-of-barovia:s-village-of-krezk", "Village of Krezk"),
            entity("cos:the-village-of-krezk:s3-village-of-krezk", "Village of Krezk"),
        ])
        assert merge.survivor == "cos:the-village-of-krezk"
        assert len(merge.losers) == 2


class TestTwoUnkeyedNodesForOneName:
    def test_they_merge_onto_the_articleless_one(self):
        [merge] = plan_merges([
            entity("cos:amber-temple", "Amber Temple"),
            entity("cos:the-amber-temple", "The Amber Temple"),
        ])
        assert merge.survivor == "cos:amber-temple"
        assert merge.survivor_name == "Amber Temple"


class TestThePlanIsStable:
    def test_re_running_it_plans_the_same_thing(self):
        """A repair that planned differently on a second run would be a repair
        nobody could review before applying."""
        entities = [
            entity("cos:the-amber-temple", "The Amber Temple"),
            entity("cos:amber-temple", "Amber Temple"),
            entity("cos:svalich-woods", "Svalich Woods"),
            entity("cos:the-lands-of-barovia:c-svalich-woods", "Svalich Woods"),
        ]
        assert plan_merges(entities) == plan_merges(list(reversed(entities)))

    def test_a_single_node_is_never_a_merge(self):
        assert plan_merges([entity("cos:strahd-von-zarovich", "Strahd von Zarovich")]) == []

    def test_a_merge_never_lists_its_survivor_as_a_loser(self):
        for merge in plan_merges([
            entity("cos:amber-temple", "Amber Temple"),
            entity("cos:the-amber-temple", "The Amber Temple"),
        ]):
            assert merge.survivor not in merge.losers
            assert isinstance(merge, Merge)


class TestAnAnthologyNameTheBookUsesBookWide:
    """`plan_globals` answers a different question from `plan_merges`: not "is
    this one place minted twice" but "did the anthology rule scope a name the
    book shares". The exception list is the book's own, so the rule is a
    function of the scheme and can be stated exactly."""

    KFTGV = BookScheme(
        prefix="kftgv",
        anthology=True,
        global_names=frozenset({"Vrakir", "The Golden Vault", "Avernus"}),
    )

    def named(self, entity_id: str, name: str, mentions: int = 0) -> dict:
        return {"id": entity_id, "name": name, "mentions": mentions}

    def test_the_survivor_lands_on_the_id_a_fresh_ingest_would_mint(self):
        """Neither half's id is the answer. Both are scoped to a chapter and
        the book says the name belongs to no chapter, so the plan has to name
        an id that does not exist yet -- or the graph and the next ingest
        disagree about a name they both got right."""
        [merge] = plan_globals(
            [
                self.named("kftgv:fire-and-darkness:vrakir", "Vrakir", 18),
                self.named("kftgv:affair-on-the-concordant-express:vrakir", "Vrakir", 1),
            ],
            self.KFTGV,
        )
        assert merge.rescope_to == "kftgv:vrakir"
        assert merge.survivor == "kftgv:fire-and-darkness:vrakir"
        assert merge.losers == ("kftgv:affair-on-the-concordant-express:vrakir",)

    def test_the_half_the_book_actually_talks_about_survives(self):
        """Only decides whose edges stay put -- the two are one entity either
        way -- but taking the node with the mentions moves the fewest."""
        [merge] = plan_globals(
            [
                self.named("kftgv:a:vrakir", "Vrakir", 1),
                self.named("kftgv:b:vrakir", "Vrakir", 18),
            ],
            self.KFTGV,
        )
        assert merge.survivor == "kftgv:b:vrakir"

    def test_a_leading_article_does_not_make_a_third_node(self):
        """`The Fated` and `Fated` are one faction in Sigil, and the graph held
        both. Normalising groups them; it is not only an alias nicety."""
        [merge] = plan_globals(
            [
                self.named("kftgv:a:the-avernus", "The Avernus", 2),
                self.named("kftgv:b:avernus", "Avernus", 1),
            ],
            self.KFTGV,
        )
        assert merge.rescope_to == "kftgv:avernus"
        assert merge.losers == ("kftgv:b:avernus",)

    def test_a_name_the_book_does_not_call_global_is_left_alone(self):
        """Two heists' armories are two armories. The anthology rule is right
        about everything not on the list, which is nearly everything."""
        assert (
            plan_globals(
                [
                    self.named("kftgv:heart-of-ashes:armory", "Armory"),
                    self.named("kftgv:vidorants-vault:t7-armory", "Armory"),
                ],
                self.KFTGV,
            )
            == []
        )

    def test_an_area_keyed_node_is_never_rescoped(self):
        """`Avernus` is the first layer of the Nine Hells AND casino area A2 in
        `The Stygian Gambit`. The book's own numbering said those apart, so the
        exception list must not reach the room -- otherwise one line meant to
        unify a plane folds a themed casino floor into it."""
        [merge] = plan_globals(
            [
                self.named("kftgv:the-stygian-gambit:a2-avernus", "Avernus", 4),
                self.named("kftgv:fire-and-darkness:avernus", "Avernus", 1),
                self.named("kftgv:affair-on-the-concordant-express:avernus", "Avernus", 1),
            ],
            self.KFTGV,
        )
        assert "kftgv:the-stygian-gambit:a2-avernus" not in merge.losers
        assert merge.survivor != "kftgv:the-stygian-gambit:a2-avernus"

    def test_a_name_already_rescoped_plans_nothing(self):
        """This runs after every re-ingest, beside the other repairs. A second
        run that planned work would mean the first one did not finish."""
        assert (
            plan_globals([self.named("kftgv:vrakir", "Vrakir", 19)], self.KFTGV) == []
        )

    def test_a_lone_node_still_on_a_chapter_is_moved(self):
        """Nothing to fold, but the id is still wrong -- and leaving it would
        mean the next ingest minted a second node beside it."""
        [merge] = plan_globals(
            [self.named("kftgv:fire-and-darkness:vrakir", "Vrakir", 18)], self.KFTGV
        )
        assert merge.losers == ()
        assert merge.rescope_to == "kftgv:vrakir"

    def test_a_campaign_books_keyed_place_is_still_keyed(self):
        """`is_area_keyed` replaces `is_keyed` only for this question, and has
        to agree with it wherever the coarser test was already right."""
        assert is_area_keyed("cos:the-lands-of-barovia:c-svalich-woods", "Svalich Woods")
        assert not is_area_keyed("cos:svalich-woods", "Svalich Woods")
        assert not is_area_keyed("kftgv:heart-of-ashes:armory", "Armory")
