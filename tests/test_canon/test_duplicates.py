"""Which nodes are one place minted twice, and which are two places.

Pure and exact: `plan_merges` takes dicts and returns a plan, so the rule that
decides whether `Kitchen` is six rooms or one can be stated as a test rather
than inferred from a graph afterwards.
"""

from backend.canon.duplicates import Merge, is_keyed, normalize, plan_merges


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
