"""The lab's session store, now that there is more than one reader.

The client used to call every session `'lab'`, so the dict held exactly one
agent and no eviction was needed or possible. Giving each browser its own id
fixed a real leak between readers -- one person's questions arriving in the
next one's context -- and made this dict grow one agent per reader with
nothing ever releasing them.
"""

import pytest

from backend.api.routes import lab


@pytest.fixture(autouse=True)
def store():
    """A store of this test's own, restored after."""
    saved = lab._SESSIONS.copy()
    lab._SESSIONS.clear()
    yield lab._SESSIONS
    lab._SESSIONS.clear()
    lab._SESSIONS.update(saved)


class _Agent:
    """Stands in for a DMAgent: the store never looks inside one."""


class TestItStaysBounded:
    def test_it_holds_everything_up_to_the_cap(self, store):
        for i in range(lab._MAX_SESSIONS):
            lab._remember(f"s{i}", _Agent())
        assert len(store) == lab._MAX_SESSIONS

    def test_going_over_evicts_the_coldest(self, store):
        for i in range(lab._MAX_SESSIONS + 3):
            lab._remember(f"s{i}", _Agent())
        assert len(store) == lab._MAX_SESSIONS
        assert "s0" not in store and "s1" not in store and "s2" not in store
        assert f"s{lab._MAX_SESSIONS + 2}" in store

    def test_the_agent_is_returned_for_chaining(self, store):
        agent = _Agent()
        assert lab._remember("s", agent) is agent


class TestUseIsWhatKeepsASessionAlive:
    def test_touching_a_session_saves_it_from_eviction(self, store):
        """Otherwise the cap evicts by age of creation and drops the session
        of whoever has been talking longest."""
        for i in range(lab._MAX_SESSIONS):
            lab._remember(f"s{i}", _Agent())
        store.move_to_end("s0")                      # what a cache hit does
        lab._remember("fresh", _Agent())
        assert "s0" in store, "the oldest-used should go, not the oldest-made"
        assert "s1" not in store

    def test_re_storing_an_existing_id_does_not_grow_the_store(self, store):
        lab._remember("s", _Agent())
        lab._remember("s", _Agent())
        assert len(store) == 1

    def test_a_replaced_agent_is_the_one_kept(self, store):
        second = _Agent()
        lab._remember("s", _Agent())
        lab._remember("s", second)
        assert store["s"] is second
