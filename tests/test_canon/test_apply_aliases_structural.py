"""A structural heading is never a spelling of anything.

`structural-headings-<book>.yaml` opens by saying what it is -- "headings the
book writes that are NOT it naming a thing" -- and one got past the seed
anyway. `Planning the Heist` heads seven of the thirteen adventures and was
grouped under `Heist for the Golden Vault`, which then held the heists of
three of them: asking about one job answered about all three.

The spanning refusal beside this could not catch it. That one asks whether a
NAME resolves to entities in several adventures, and a heading resolves to no
entity at all.
"""

from backend.canon.aliases import normalize
from backend.scripts.apply_aliases import _structural_for, plan

STRUCTURAL = frozenset({normalize("Planning the Heist"), normalize("Treasure")})


def _group(canonical, *names):
    return [{"canonical": canonical, "names": list(names)}]


class TestScaffoldingIsRefused:
    def test_a_group_holding_a_structural_heading_is_refused(self):
        merges, refused = plan(
            _group("Heist for the Golden Vault",
                   "Heist for the Golden Vault", "Planning the Heist"),
            {"Heist for the Golden Vault": ["kftgv:the-stygian-gambit:heist"],
             "Planning the Heist": ["kftgv:axe-from-the-grave:planning"]},
            STRUCTURAL,
        )
        assert not merges
        assert any("Planning the Heist" in r for r in refused)
        assert any("scaffolding" in r for r in refused)

    def test_a_group_of_real_names_still_merges(self):
        """The guard must not swallow the ordinary case it sits in front of."""
        merges, refused = plan(
            _group("Varrin Axebreaker", "Varrin Axebreaker", "Varrin"),
            {"Varrin Axebreaker": ["kftgv:prisoner-13:varrin-axebreaker"],
             "Varrin": ["kftgv:prisoner-13:varrin"]},
            STRUCTURAL,
        )
        assert merges, refused

    def test_with_no_seed_nothing_extra_is_refused(self):
        """The default is empty, so a book without the seed behaves as before."""
        merges, _ = plan(
            _group("Heist for the Golden Vault",
                   "Heist for the Golden Vault", "Planning the Heist"),
            {"Heist for the Golden Vault": ["kftgv:the-stygian-gambit:heist"],
             "Planning the Heist": ["kftgv:the-stygian-gambit:planning"]},
        )
        assert merges


class TestTheBooksOwnSeedIsRead:
    def test_kftgv_scaffolding_includes_the_heading_that_got_through(self):
        assert normalize("Planning the Heist") in _structural_for("kftgv")

    def test_a_real_name_is_not_scaffolding(self):
        assert normalize("Jenna Bean") not in _structural_for("kftgv")

    def test_each_book_reads_its_own_file(self):
        """One seed shared between them would be each book carrying the
        other's exceptions -- `Planning the Heist` heads nothing in Barovia."""
        assert _structural_for("cos") != _structural_for("kftgv")
