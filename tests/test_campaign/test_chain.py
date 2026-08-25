"""The running order's rules, checked by applying plans and reading the order.

Asserted on the RESULTING ORDER rather than on the pointer pairs, because the
pairs are an implementation of the order and the order is what a DM sees. A test
that pinned the pairs would pass on a plan that produced them in a chain that
had come apart somewhere else.
"""

from backend.campaign.chain import (
    Rewire,
    adjacent_homebrew,
    insert_plan,
    integrity,
    move_plan,
    position_for,
    remove_plan,
    seed_plan,
    walk,
)

BOOK = ["kftgv:prisoner-13#5", "kftgv:prisoner-13#6", "kftgv:prisoner-13#7",
        "kftgv:prisoner-13#8", "kftgv:prisoner-13#9"]
SEA = "hb:p13-home:sea-battle"
STORM = "hb:p13-home:storm"
TREK = "kftgv:prisoner-13#7"
REVELS = "kftgv:prisoner-13#8"


def apply(links: frozenset, start, rewire: Rewire):
    """What the chain looks like after a plan. Mirrors what the writer does."""
    after = frozenset((set(links) - set(rewire.unlink)) | set(rewire.link))
    return after, (rewire.start if rewire.sets_start else start)


def seeded(ids=None):
    ids = BOOK if ids is None else ids
    plan = seed_plan(ids)
    return frozenset(plan.link), plan.start


def order(links, start):
    found = walk(links, start)
    assert found.stopped == "end", found.stopped
    return list(found.order)


class TestSeed:
    def test_the_chain_is_the_books_own_order(self):
        links, start = seeded()
        assert order(links, start) == BOOK

    def test_an_empty_book_seeds_nothing(self):
        """A pure-homebrew campaign starts here, and it is not an error."""
        plan = seed_plan([])
        assert plan.noop and plan.start is None and not plan.link

    def test_a_seeded_chain_is_sound(self):
        links, start = seeded()
        assert integrity(links, start) == ()


class TestInsert:
    def test_a_scene_lands_after_its_anchor(self):
        """The sea battle, inside the voyage."""
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=TREK))
        assert order(links, start) == BOOK[:3] + [SEA] + BOOK[3:]
        assert integrity(links, start) == ()

    def test_inserting_after_the_last_section_appends(self):
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=BOOK[-1]))
        assert order(links, start)[-1] == SEA

    def test_inserting_at_the_head_moves_the_start(self):
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=None))
        assert order(links, start)[0] == SEA
        assert integrity(links, start) == ()

    def test_the_first_section_of_an_empty_campaign_becomes_the_start(self):
        """A campaign drawing on no book. `STARTS_AT` is born here."""
        plan = insert_plan(frozenset(), None, SEA, after=None)
        assert plan.start == SEA and not plan.link
        links, start = apply(frozenset(), None, plan)
        assert order(links, start) == [SEA]

    def test_two_scenes_at_one_anchor_keep_their_order(self):
        """No `rank` needed: the chain says which is which."""
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=TREK))
        links, start = apply(links, start, insert_plan(links, start, STORM, after=SEA))
        assert order(links, start) == BOOK[:3] + [SEA, STORM] + BOOK[3:]
        assert integrity(links, start) == ()


class TestRemove:
    def test_skipping_splices_the_order_shut(self):
        links, start = seeded()
        links, start = apply(links, start, remove_plan(links, start, TREK))
        assert order(links, start) == [s for s in BOOK if s != TREK]
        assert integrity(links, start) == ()

    def test_skipping_the_head_moves_the_start(self):
        links, start = seeded()
        links, start = apply(links, start, remove_plan(links, start, BOOK[0]))
        assert order(links, start) == BOOK[1:]
        assert integrity(links, start) == ()

    def test_skipping_the_tail_leaves_a_sound_chain(self):
        links, start = seeded()
        links, start = apply(links, start, remove_plan(links, start, BOOK[-1]))
        assert order(links, start) == BOOK[:-1]
        assert integrity(links, start) == ()

    def test_skipping_the_only_section_empties_the_chain(self):
        links, start = seeded([SEA])
        links, start = apply(links, start, remove_plan(links, start, SEA))
        assert order(links, start) == []
        assert integrity(links, start) == ()

    def test_skipping_something_absent_is_a_reported_noop(self):
        """"already skipped" and "skipped it for you" are different answers."""
        links, start = seeded()
        assert remove_plan(links, start, "kftgv:prisoner-13#99").noop


class TestMove:
    def test_a_section_moves_later(self):
        links, start = seeded()
        links, start = apply(links, start, move_plan(links, start, BOOK[1], after=BOOK[3]))
        assert order(links, start) == [BOOK[0], BOOK[2], BOOK[3], BOOK[1], BOOK[4]]
        assert integrity(links, start) == ()

    def test_a_section_moves_earlier(self):
        links, start = seeded()
        links, start = apply(links, start, move_plan(links, start, BOOK[3], after=BOOK[0]))
        assert order(links, start) == [BOOK[0], BOOK[3], BOOK[1], BOOK[2], BOOK[4]]
        assert integrity(links, start) == ()

    def test_moving_a_section_to_the_head(self):
        links, start = seeded()
        links, start = apply(links, start, move_plan(links, start, BOOK[2], after=None))
        assert order(links, start) == [BOOK[2], BOOK[0], BOOK[1], BOOK[3], BOOK[4]]
        assert integrity(links, start) == ()

    def test_moving_the_head_elsewhere(self):
        links, start = seeded()
        links, start = apply(links, start, move_plan(links, start, BOOK[0], after=BOOK[2]))
        assert order(links, start) == [BOOK[1], BOOK[2], BOOK[0], BOOK[3], BOOK[4]]
        assert integrity(links, start) == ()

    def test_moving_a_section_after_its_own_predecessor_changes_nothing(self):
        """THE CANCELLING-POINTER TRAP. Written directly, this emits pairs that
        undo each other and two that survive to corrupt the order."""
        links, start = seeded()
        moved = move_plan(links, start, BOOK[2], after=BOOK[1])
        links, start = apply(links, start, moved)
        assert order(links, start) == BOOK
        assert integrity(links, start) == ()

    def test_a_section_cannot_follow_itself(self):
        links, start = seeded()
        assert move_plan(links, start, BOOK[1], after=BOOK[1]).noop


class TestIntegrity:
    def test_a_forked_chain_is_caught(self):
        """Two successors: the order silently becomes ambiguous."""
        links, start = seeded()
        broken = links | {(BOOK[0], BOOK[3])}
        assert any("outgoing" in p for p in integrity(broken, start))

    def test_a_severed_chain_is_caught(self):
        """The failure that loses the back half of a running order."""
        links, start = seeded()
        broken = frozenset(links - {(BOOK[1], BOOK[2])})
        assert any("unreachable" in p for p in integrity(broken, start))

    def test_a_loop_is_caught_rather_than_spun_on(self):
        links, start = seeded()
        looped = links | {(BOOK[-1], BOOK[0])}
        assert integrity(looped, start)
        assert walk(looped, start, bound=50).looped

    def test_a_chain_with_links_and_no_start_is_caught(self):
        links, _ = seeded()
        assert any("no start" in p for p in integrity(links, None))

    def test_a_start_that_is_not_the_head_is_caught(self):
        links, _ = seeded()
        assert any("predecessor" in p for p in integrity(links, BOOK[2]))


class TestPositionFor:
    def test_a_new_section_follows_its_nearest_placed_predecessor(self):
        """The reconcile case: a chapter harvested after seeding."""
        in_chain = frozenset(BOOK) - {BOOK[2]}
        assert position_for(BOOK, in_chain, BOOK[2]) == BOOK[1]

    def test_it_skips_over_other_unplaced_sections(self):
        in_chain = frozenset({BOOK[0], BOOK[4]})
        assert position_for(BOOK, in_chain, BOOK[3]) == BOOK[0]

    def test_the_first_section_has_no_predecessor(self):
        assert position_for(BOOK, frozenset(BOOK[1:]), BOOK[0]) is None


class TestAdjacentHomebrew:
    def test_a_scene_after_the_anchor_rides_along(self):
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=TREK))
        before, after, cut = adjacent_homebrew(links, TREK)
        assert after == (SEA,) and before == () and cut == 0

    def test_a_scene_before_the_anchor_rides_along_too(self):
        """Chained just before Revel's End is as adjacent as just after Trek."""
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=TREK))
        before, after, _ = adjacent_homebrew(links, REVELS)
        assert before == (SEA,) and after == ()

    def test_it_stops_at_the_first_canon_section(self):
        """Walking past canon would drag in the neighbourhood of something
        retrieval never retrieved."""
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=TREK))
        before, after, _ = adjacent_homebrew(links, BOOK[0])
        assert after == () and before == ()

    def test_contiguous_scenes_all_ride(self):
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=TREK))
        links, start = apply(links, start, insert_plan(links, start, STORM, after=SEA))
        _, after, _ = adjacent_homebrew(links, TREK)
        assert after == (SEA, STORM)

    def test_the_bound_counts_what_it_cut(self):
        """A canon section dense with insertions must not drag them all in --
        and must not hide that it stopped."""
        links, start = seeded()
        previous = TREK
        for i in range(5):
            scene = f"hb:p13-home:scene-{i}"
            links, start = apply(links, start, insert_plan(links, start, scene, after=previous))
            previous = scene
        _, after, cut = adjacent_homebrew(links, TREK, bound=3)
        assert len(after) == 3 and cut == 2

    def test_a_section_with_no_insertions_brings_nothing(self):
        links, start = seeded()
        assert adjacent_homebrew(links, TREK) == ((), (), 0)


class TestAPartiallyAppliedPlanIsAlwaysCaught:
    """Drop any ONE pointer from a plan and `integrity` must object.

    This is what makes the transaction safe. A rewire is several pointer
    changes; if some subset could apply and still look sound, a half-applied
    write would leave a DM's running order quietly wrong instead of rolling
    back. Every operation is checked, not just insert, because they emit
    different shapes -- skip removes two and adds one, move does both.
    """

    def _plans(self):
        links, start = seeded()
        yield "insert", links, start, insert_plan(links, start, SEA, after=TREK)
        yield "insert-head", links, start, insert_plan(links, start, SEA, after=None)
        yield "remove", links, start, remove_plan(links, start, TREK)
        yield "remove-head", links, start, remove_plan(links, start, BOOK[0])
        yield "move-later", links, start, move_plan(links, start, BOOK[1], after=BOOK[3])
        yield "move-earlier", links, start, move_plan(links, start, BOOK[3], after=BOOK[0])

    def _membership(self, links, start, plan):
        """What the chain should hold once the plan has fully applied."""
        after, moved = apply(links, start, plan)
        return frozenset(walk(after, moved).order)

    def test_the_whole_plan_is_sound(self):
        for name, links, start, plan in self._plans():
            after, moved = apply(links, start, plan)
            assert integrity(after, moved, self._membership(links, start, plan)) == (), name

    def test_dropping_any_added_pointer_breaks_it(self):
        for name, links, start, plan in self._plans():
            expected = self._membership(links, start, plan)
            for i in range(len(plan.link)):
                partial = Rewire(
                    unlink=plan.unlink,
                    link=plan.link[:i] + plan.link[i + 1:],
                    start=plan.start,
                    sets_start=plan.sets_start,
                )
                after, moved = apply(links, start, partial)
                assert integrity(after, moved, expected) != (), f"{name}: dropped link {i}"

    def test_skipping_any_removal_breaks_it(self):
        for name, links, start, plan in self._plans():
            expected = self._membership(links, start, plan)
            for i in range(len(plan.unlink)):
                partial = Rewire(
                    unlink=plan.unlink[:i] + plan.unlink[i + 1:],
                    link=plan.link,
                    start=plan.start,
                    sets_start=plan.sets_start,
                )
                after, moved = apply(links, start, partial)
                assert integrity(after, moved, expected) != (), f"{name}: kept unlink {i}"

    def test_forgetting_to_move_the_head_breaks_it(self):
        """The `sets_start` half. A plan whose pointers all applied but whose
        start was not updated leaves a head with a predecessor, or one pointing
        at a section no longer in the chain."""
        links, start = seeded()
        for name, plan in (
            ("insert-head", insert_plan(links, start, SEA, after=None)),
            ("remove-head", remove_plan(links, start, BOOK[0])),
        ):
            assert plan.sets_start, name
            after, _ = apply(links, start, Rewire(unlink=plan.unlink, link=plan.link))
            assert integrity(after, start) != (), name


class TestSectionsCannotVanishSilently:
    """`expected` is what catches a section falling out of the chain entirely.

    Pinned separately from the partial-plan sweep because it is the failure
    that motivated the parameter: a chain missing a section is internally
    perfect -- every pointer sound, everything reachable -- and only a caller
    who knows what SHOULD be there can tell.
    """

    def test_a_lost_section_is_invisible_without_expected(self):
        links, start = seeded()
        shortened = frozenset({(BOOK[0], BOOK[1]), (BOOK[1], BOOK[2])})
        assert integrity(shortened, start) == ()

    def test_and_is_caught_with_it(self):
        links, start = seeded()
        shortened = frozenset({(BOOK[0], BOOK[1]), (BOOK[1], BOOK[2])})
        problems = integrity(shortened, start, frozenset(BOOK))
        assert any("fell out of the chain" in p for p in problems)

    def test_a_stowaway_section_is_caught_too(self):
        links, start = seeded()
        links, start = apply(links, start, insert_plan(links, start, SEA, after=TREK))
        problems = integrity(links, start, frozenset(BOOK))
        assert any("unexpected" in p for p in problems)
