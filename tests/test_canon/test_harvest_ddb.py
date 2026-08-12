"""Harvest tests. No network: the MCP reader seam is replaced by a fake server.

The fake reproduces `readBook`'s response framing character for character --
the two-line header, the "End of chapter" range note, the truncation notice --
because every one of those strings is something `strip_block` must remove
without touching the rendered text on either side of it. A looser fake would
let a whitespace bug through, and a whitespace bug in a paginated read shifts
every subsequent offset.
"""

import json

import pytest

from backend.scripts import harvest_ddb


def render(book: str, chapter: str | None, text: str, offset: int, limit: int) -> str:
    """Reproduce ddb-mcp's readBook framing for a chapter that renders to `text`."""
    url = f"https://www.dndbeyond.com/sources/{book}" + (f"/{chapter}" if chapter else "")
    header = f"# {book}" + (f" / {chapter}" if chapter else "") + f"\nURL: {url}"
    total = len(text)
    start = max(0, offset)
    size = max(1, limit)
    end = min(total, start + size)
    if start >= total:
        return f"{header}\n\n[No content at offset {start}. This chapter renders to {total} characters; valid offsets are 0-{max(0, total - 1)}.]"  # noqa: E501
    piece = text[start:end]
    if end >= total:
        note = f"\n[Characters {start}-{end} of {total}. End of chapter.]\n\n" if start else ""
        return f"{header}{chr(10) + note if note else chr(10)}\n{piece}"
    call = f'ddb_read_book(book_slug="{book}", offset={end}, limit={size})'
    return (
        f"{header}\n\n{piece}\n\n"
        f"[Content truncated: characters {start}-{end} of {total} total rendered "
        f"characters. To continue, call {call}]"
    )


class FakeServer:
    """An in-memory stand-in for the dndbeyond MCP server."""

    def __init__(self, toc: str, chapters: dict[str, str]) -> None:
        self.toc = toc
        self.chapters = chapters
        self.calls: list[tuple[str | None, int]] = []
        self.fail_once: set[str] = set()

    async def __call__(self, book: str, chapter: str | None, offset: int, limit: int) -> str:
        self.calls.append((chapter, offset))
        if chapter in self.fail_once:
            self.fail_once.discard(chapter)
            raise RuntimeError("navigation timeout")
        if chapter is None:
            return render(book, None, self.toc, offset, limit)
        text = self.chapters.get(chapter, "Back to Top\n\nPage Not Found\n\nSorry!")
        return render(book, chapter, text, offset, limit)


TOC = """# dnd/cos
URL: https://www.dndbeyond.com/sources/dnd/cos

Unravel the mysteries of Ravenloft in this Appendices blurb.

### Related Sources

- Van Richten's Guide to Ravenloft

## Contents

### Foreword

### Ch. 11: Van Richten's Tower

- Areas of the Tower

### Appendices

- Appendix B: Death House

- Appendix C: Treasures

### Poster Map

- Barovia

- Ch. 11: Van Richten's Tower
"""

CHAPTERS = {
    "foreword-ravenloft-revisited": "# Foreword\n\nRavenloft revisited.",
    "van-richtens-tower": "# Van Richten's Tower\n\n### K1. Base of the Tower\n",
    "appendix-b-death-house": "# Death House\n",
    "appendix-c-treasures": "# Treasures\n",
}

OVERRIDES = {"Foreword": "foreword-ravenloft-revisited"}


def make_server(**chapters: str) -> FakeServer:
    return FakeServer(TOC, {**CHAPTERS, **chapters})


# --- slug derivation and table-of-contents parsing ---------------------------


def test_derive_slug_strips_the_chapter_number_and_the_apostrophe():
    assert harvest_ddb.derive_slug("Ch. 11: Van Richten's Tower") == "van-richtens-tower"
    assert harvest_ddb.derive_slug("Ch. 4: Castle Ravenloft") == "castle-ravenloft"


def test_derive_slug_keeps_the_appendix_letter():
    """Appendix slugs include their prefix, unlike numbered chapters."""
    derived = harvest_ddb.derive_slug("Appendix D: Monsters and NPCs")
    assert derived == "appendix-d-monsters-and-npcs"


def test_parse_toc_ignores_headings_above_the_contents_list():
    """The blurb above `## Contents` names chapters it does not link to."""
    groups = harvest_ddb.parse_toc(TOC)
    assert [g.title for g in groups] == [
        "Foreword",
        "Ch. 11: Van Richten's Tower",
        "Appendices",
        "Poster Map",
    ]
    assert groups[2].children == ["Appendix B: Death House", "Appendix C: Treasures"]


# --- pagination --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_short_chapter_costs_one_call():
    server = make_server()
    markdown, calls = await harvest_ddb.read_chapter(server, "dnd/cos", "appendix-c-treasures")
    assert calls == 1
    assert markdown == "# Treasures\n"


@pytest.mark.asyncio
async def test_pagination_reassembles_a_long_chapter_character_for_character():
    """Three 50k blocks must rejoin into the original 120k, not 120k-ish."""
    body = "".join(f"### K{i}. Room {i}\n\nA room.\n\n" for i in range(4000))
    assert len(body) > 2 * harvest_ddb.DEFAULT_PAGE_SIZE
    server = make_server(castle_ravenloft=body)
    server.chapters["castle-ravenloft"] = body

    markdown, calls = await harvest_ddb.read_chapter(server, "dnd/cos", "castle-ravenloft")

    assert markdown == body
    assert calls == len(body) // harvest_ddb.DEFAULT_PAGE_SIZE + 1
    assert [offset for _, offset in server.calls] == [
        i * harvest_ddb.DEFAULT_PAGE_SIZE for i in range(calls)
    ]


@pytest.mark.asyncio
async def test_pagination_preserves_a_newline_that_lands_on_a_block_boundary():
    """A slice may begin or end with whitespace; stripping it corrupts the join."""
    body = "a" * 99 + "\n" + "b" * 100
    server = make_server()
    server.chapters["boundary"] = body

    markdown, _ = await harvest_ddb.read_chapter(server, "dnd/cos", "boundary", page_size=100)

    assert markdown == body


@pytest.mark.asyncio
async def test_a_chapter_that_reassembles_short_is_rejected():
    """The server states the total; a join that misses it is not the chapter."""

    async def lying_reader(book, chapter, offset, limit):
        text = render(book, chapter, "x" * 200, offset, limit)
        return text.replace("of 200 total", "of 500 total")

    with pytest.raises(RuntimeError, match="reassembled 200 characters, server reported 500"):
        await harvest_ddb.read_chapter(lying_reader, "dnd/cos", "castle-ravenloft", page_size=100)


@pytest.mark.asyncio
async def test_an_offset_that_does_not_advance_raises_instead_of_looping():
    async def stuck_reader(book, chapter, offset, limit):
        return (
            f"# {book} / {chapter}\nURL: u\n\nchunk\n\n"
            "[Content truncated: characters 0-0 of 999 total rendered characters. "
            'To continue, call ddb_read_book(book_slug="x", offset=0, limit=10)]'
        )

    with pytest.raises(RuntimeError, match="offset did not advance"):
        await harvest_ddb.read_chapter(stuck_reader, "dnd/cos", "castle-ravenloft")


# --- resumability ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_complete_chapter_is_not_refetched(tmp_path):
    server = make_server()
    first = await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )
    fetched = [c for c, _ in server.calls]

    second = await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-12", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    assert first["chapter_count"] == second["chapter_count"] == 4
    assert sorted(second["skipped"]) == sorted(c["slug"] for c in second["chapters"])
    # No cached chapter is re-read. The table of contents and the 404 probes
    # that identify container groups are re-run deliberately: caching a miss
    # would hide a chapter the publisher added since the last harvest.
    rerun = [c for c, _ in server.calls[len(fetched):]]
    assert not set(rerun) & {c["slug"] for c in second["chapters"]}
    assert rerun == [None, "appendices", "poster-map", "barovia"]
    # The cached sidecar keeps its original fetch date, not the rerun's.
    assert {c["fetched_on"] for c in second["chapters"]} == {"2026-08-11"}


@pytest.mark.asyncio
async def test_a_truncated_markdown_file_is_refetched(tmp_path):
    """A run killed mid-write leaves text the sidecar's count does not match."""
    server = make_server()
    await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )
    (tmp_path / "appendix-c-treasures.md").write_text("# Trea")
    before = len(server.calls)

    await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    assert "appendix-c-treasures" in [c for c, _ in server.calls[before:]]
    assert (tmp_path / "appendix-c-treasures.md").read_text() == "# Treasures\n"


@pytest.mark.asyncio
async def test_a_sidecar_that_never_claimed_completeness_is_refetched(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "appendix-c-treasures.md").write_text("# Treasures\n")
    (tmp_path / "appendix-c-treasures.json").write_text(
        json.dumps(
            {
                "slug": "appendix-c-treasures",
                "title": "Appendix C: Treasures",
                "chars": 12,
                "calls": 1,
                "fetched_on": "2026-08-01",
                "complete": False,
            }
        )
    )
    server = make_server()

    await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    sidecar = json.loads((tmp_path / "appendix-c-treasures.json").read_text())
    assert sidecar["complete"] is True
    assert sidecar["fetched_on"] == "2026-08-11"


@pytest.mark.asyncio
async def test_a_failed_chapter_is_reported_and_the_walk_continues(tmp_path):
    server = make_server()
    server.fail_once.add("appendix-c-treasures")

    first = await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    assert [f["slug"] for f in first["failed"]] == ["appendix-c-treasures"]
    assert first["chapter_count"] == 3
    assert not (tmp_path / "appendix-c-treasures.md").exists()

    second = await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    assert second["failed"] == []
    assert second["chapter_count"] == 4
    assert (tmp_path / "appendix-c-treasures.md").exists()


# --- resolving chapters that the table of contents does not spell out --------


@pytest.mark.asyncio
async def test_an_override_is_used_where_the_title_does_not_derive_the_slug(tmp_path):
    """"Foreword" lives at "foreword-ravenloft-revisited"; no rule finds that."""
    server = make_server()

    manifest = await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    assert "foreword-ravenloft-revisited" in [c["slug"] for c in manifest["chapters"]]
    assert manifest["unresolved"] == ["Poster Map"]


@pytest.mark.asyncio
async def test_without_the_override_the_foreword_is_reported_unresolved(tmp_path):
    server = make_server()

    manifest = await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, log=lambda _: None
    )

    assert "Foreword" in manifest["unresolved"]
    assert "foreword-ravenloft-revisited" not in [c["slug"] for c in manifest["chapters"]]


@pytest.mark.asyncio
async def test_a_container_group_yields_its_children_as_chapters(tmp_path):
    """"Appendices" has no page of its own; its bullets are the real chapters."""
    server = make_server()

    manifest = await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    slugs = [c["slug"] for c in manifest["chapters"]]
    assert "appendices" not in slugs
    assert ["appendix-b-death-house", "appendix-c-treasures"] == slugs[2:]


@pytest.mark.asyncio
async def test_a_group_whose_only_hit_is_another_chapter_is_not_called_resolved(tmp_path):
    """"Poster Map" lists a bullet that derives chapter 11's slug, not its own.

    Counting that as a resolution would report the group as harvested when
    nothing belonging to it was fetched.
    """
    server = make_server()

    manifest = await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    assert manifest["unresolved"] == ["Poster Map"]
    assert manifest["aliased"] == [
        {"group": "Poster Map", "children": ["Ch. 11: Van Richten's Tower"]}
    ]
    assert [c["slug"] for c in manifest["chapters"]].count("van-richtens-tower") == 1


@pytest.mark.asyncio
async def test_a_404_page_is_never_cached_as_a_chapter(tmp_path):
    server = make_server()

    await harvest_ddb.harvest(
        server, "dnd/cos", "2026-08-11", tmp_path, overrides=OVERRIDES, log=lambda _: None
    )

    assert not (tmp_path / "poster-map.md").exists()
    assert not (tmp_path / "appendices.md").exists()
