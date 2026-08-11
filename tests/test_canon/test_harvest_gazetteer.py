"""Batching tests for the harvest script. No network: the fetch seam is replaced."""

from backend.scripts import harvest_gazetteer


def test_fetch_pages_asks_for_at_most_fifty_titles_per_call(monkeypatch):
    """MediaWiki caps a titles query at 50; 677 entities must cost ~14 calls, not one."""
    calls: list[list[str]] = []

    def fake_fetch(params, api_url=harvest_gazetteer.API_URL, timeout=30):
        titles = params["titles"].split("|")
        calls.append(titles)
        return {"query": {"pages": [{"title": t, "missing": True} for t in titles]}}

    monkeypatch.setattr(harvest_gazetteer, "fetch", fake_fetch)
    monkeypatch.setattr(harvest_gazetteer.time, "sleep", lambda _: None)

    pages = harvest_gazetteer.fetch_pages([f"Entity {i}" for i in range(121)])

    assert [len(c) for c in calls] == [50, 50, 21]
    assert len(pages) == 121
