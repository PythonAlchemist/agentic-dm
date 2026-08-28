"""Carrying a read alias seed into the graph, and what it refuses to carry.

`propose_aliases` asks a model which names are one thing and writes a file;
this is the half that applies it, after a person has read it. The refusals are
the interesting part: a merge is irreversible, so everything it will not do has
to be a decision rather than an accident.
"""

from backend.scripts.apply_aliases import chapter_of, plan
from backend.scripts.audit_scope import _KEYED


class TestWhichAdventureAnIdBelongsTo:
    def test_the_middle_segment_is_the_scope(self):
        assert chapter_of("kftgv:the-stygian-gambit:the-heist") == "the-stygian-gambit"

    def test_an_adventure_itself_is_scoped_to_none(self):
        """`kftgv:prisoner-13` is the adventure, not something inside one, so
        it has no middle segment to read."""
        assert chapter_of("kftgv:prisoner-13") == ""


class TestAGroupMayNotSpanAdventures:
    """Every heist in this book is a heist, so `Heist`, `The Heist`, `Planning
    the Heist`, `Casino Heist` and `Vidorant's Next Heist` came back from the
    coreference model as one thing. One QUEST node scoped to the Stygian Gambit
    ended up holding the jobs of four separate adventures -- with mentions in
    chapters its own scope forbids it from being scanned in."""

    SPANNING = [{
        "canonical": "Heist for the Golden Vault",
        "names": ["Heist for the Golden Vault", "Casino Heist", "Vidorant's Next Heist"],
    }]
    INDEX = {
        "Heist for the Golden Vault": ["kftgv:the-stygian-gambit:heist-for-the-golden-vault"],
        "Casino Heist": ["kftgv:the-stygian-gambit:casino-heist"],
        "Vidorant's Next Heist": ["kftgv:vidorants-vault:vidorants-next-heist"],
    }

    def test_it_is_refused_whole(self):
        merges, refused = plan(self.SPANNING, self.INDEX)
        assert merges == []
        assert len(refused) == 1

    def test_the_refusal_names_the_adventures_it_reached_across(self):
        """A grouping silently dropped is indistinguishable from one never
        proposed, which is the shape of defect this package keeps finding in
        itself."""
        _, refused = plan(self.SPANNING, self.INDEX)
        assert "the-stygian-gambit" in refused[0]
        assert "vidorants-vault" in refused[0]

    def test_one_adventure_still_merges(self):
        """The guard must not stop the thing this script is for: two spellings
        of one job inside one adventure ARE one job."""
        groups = [{
            "canonical": "Retrieve the key",
            "names": ["Retrieve the key", "Retrieve the key from Prisoner 13"],
        }]
        index = {
            "Retrieve the key": ["kftgv:prisoner-13:retrieve-the-key"],
            "Retrieve the key from Prisoner 13": [
                "kftgv:prisoner-13:retrieve-the-key-from-prisoner-13"
            ],
        }
        merges, refused = plan(groups, index)
        assert refused == []
        assert merges[0].survivor == "kftgv:prisoner-13:retrieve-the-key"
        assert merges[0].losers == ("kftgv:prisoner-13:retrieve-the-key-from-prisoner-13",)

    def test_a_book_wide_member_does_not_count_as_a_second_adventure(self):
        """A name the book holds book-wide belongs to no one adventure. It is
        `""`, not a third chapter, and grouping it with one is the case this
        script exists to apply."""
        groups = [{
            "canonical": "Golden Vault",
            "names": ["Golden Vault", "The Golden Vault", "Vault Job"],
        }]
        index = {
            "Golden Vault": ["kftgv:golden-vault"],
            "The Golden Vault": ["kftgv:golden-vault-the"],
            "Vault Job": ["kftgv:prisoner-13:vault-job"],
        }
        merges, refused = plan(groups, index)
        assert refused == [], refused
        assert len(merges) == 1

    def test_the_older_refusal_still_fires(self):
        """A name resolving to several entities is the anthology rule from the
        other side, and was here first."""
        groups = [{"canonical": "Hallway", "names": ["Hallway", "Arrow Slit Hallway"]}]
        index = {
            "Hallway": ["kftgv:heart-of-ashes:s2-hallway", "kftgv:tockworths:hallway"],
            "Arrow Slit Hallway": ["kftgv:heart-of-ashes:arrow-slit-hallway"],
        }
        merges, refused = plan(groups, index)
        assert merges == []
        assert "more than one entity" in refused[0]


class TestAKeyedAreaBelongsToOneAdventure:
    """The audit's one verdict that needs no judgement. Counting mentions was
    tried first and is wrong about exactly the cases the anthology rule exists
    for: `Laundry Room` has one mention at home and two abroad, which
    arithmetic reads as book-wide and a reader reads as a room in one heist."""

    def test_a_map_key_is_recognised(self):
        for slug in ("c10-laundry-room", "b3-prison-tower", "g14-upstairs-foyer",
                     "r17-cells", "s2-hallway", "e7-temple-car"):
            assert _KEYED.match(slug), slug

    def test_a_person_is_not_a_room(self):
        for slug in ("honorary-mayor-jenna-bean", "varrin-axebreaker",
                     "heist-for-the-golden-vault", "the-vault"):
            assert not _KEYED.match(slug), slug
