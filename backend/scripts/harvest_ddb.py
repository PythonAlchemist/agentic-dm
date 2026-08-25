#!/usr/bin/env python3
"""Harvest an owned D&D Beyond book into a local markdown cache.

This replaces the vision-transcription stage for good. That stage rendered
`data/cos.pdf` to page images and asked a vision model to transcribe each one,
which cost money per run, served exactly one book, and produced markdown whose
heading levels were assigned essentially at random. The D&D Beyond MCP server
returns the publisher's own markup, so heading levels, tables and boxed
read-aloud text arrive intact, and the same reader serves every book the user
owns.

Nothing here writes to Neo4j and nothing here calls an LLM. The output is a
directory of markdown files plus one JSON sidecar per chapter, under a
gitignored path -- the text is copyrighted and must never be committed.

Resumability is the point of the sidecars. A 25-chapter walk takes minutes of
browser navigation, so a transient failure on chapter 20 must not cost the
first nineteen: a chapter whose sidecar says `complete` and whose character
count still matches the file on disk is skipped without a network call.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

DEFAULT_ROOT = Path("data/ddb")

# Where per-book slug overrides live. These files hold slugs only -- no book
# text -- so they are committed, unlike everything under `data/`.
SLUG_DIR = Path(__file__).parent / "ddb_slugs"

# The MCP server renders D&D Beyond's 404 page like any other page, so a wrong
# slug comes back as a successful call whose body says this. There is no status
# code to check: this string is the only signal.
PAGE_NOT_FOUND = "Page Not Found"

# `readBook`'s own default block size. Matching it means the pagination loop is
# exercised on exactly the chapters the server would have truncated anyway.
DEFAULT_PAGE_SIZE = 50000

# The two-line preamble every readBook response carries: "# <book> / <chapter>"
# then "URL: ...".
_HEADER_LINES = 2

# Emitted only when a final block started at a non-zero offset -- i.e. on the
# last block of a paginated read. Matched after the header's trailing blank
# line has been removed, which is why it is not itself newline-prefixed.
_RANGE_NOTE = re.compile(r"\A\[Characters \d+-\d+ of \d+\. End of chapter\.\]\n\n\n")

# Emitted whenever a block was cut short. The numbers are character positions
# in the chapter's fully rendered markdown, which is what makes exact
# reassembly checkable: the parts must sum to the stated total.
_TRUNCATION = re.compile(
    r"\n\n\[Content truncated: characters (\d+)-(\d+) of (\d+) total rendered "
    r"characters\. To continue, call [^\]]*\]\Z"
)

# A slug is lowercase alphanumerics joined by single hyphens. Apostrophes are
# dropped rather than hyphenated -- D&D Beyond spells chapter 11
# "van-richtens-tower", not "van-richten-s-tower".
_APOSTROPHES = re.compile(r"[’']")
_NON_SLUG = re.compile(r"[^a-z0-9]+")

# "Ch. 4: Castle Ravenloft" -> "Castle Ravenloft". Appendices keep their
# prefix, because their slugs do too ("appendix-b-death-house").
_CHAPTER_PREFIX = re.compile(r"^ch\.?\s*\d+\s*[:.]\s*", re.IGNORECASE)

_TOC_HEADING = re.compile(r"^###\s+(?!#)(.+?)\s*$", re.MULTILINE)
_TOC_ITEM = re.compile(r"^-\s+(.+?)\s*$", re.MULTILINE)
_CONTENTS = re.compile(r"^##\s+Contents\s*$", re.MULTILINE | re.IGNORECASE)

# `book_slug` is a path ("dnd/cos"), so it cannot name a file directly.
_PATH_SEP = re.compile(r"[/\\]+")

# (book_slug, chapter_slug, offset, limit) -> rendered block. Async so the
# production reader can hold one MCP session open across the whole walk;
# tests pass a plain coroutine and never touch the network.
Reader = Callable[[str, str | None, int, int], Awaitable[str]]


@dataclass
class TocGroup:
    """One `###` entry in a table of contents, with its bullet children.

    A group is usually a chapter whose children are in-page anchors ("Special
    Events"). Sometimes -- "Appendices" -- the group is a container with no
    page of its own and the children are the real chapters. Which one it is
    cannot be read off the text, so `harvest` finds out by asking.
    """

    title: str
    children: list[str] = field(default_factory=list)


@dataclass
class Block:
    """One readBook response with its framing removed."""

    content: str
    next_offset: int | None
    total: int | None


@dataclass
class ChapterRecord:
    """The sidecar written beside each cached chapter."""

    slug: str
    title: str
    chars: int
    calls: int
    fetched_on: str
    complete: bool = True


def slug_filename(book_slug: str) -> str:
    """Flatten a book slug so it can name a directory: `dnd/cos` -> `dnd-cos`."""
    return _PATH_SEP.sub("-", book_slug).strip("-")


def derive_slug(title: str) -> str:
    """Guess a chapter's URL slug from its table-of-contents title.

    Right for 24 of Curse of Strahd's 25 chapters. The twenty-fifth, whose
    title is "Foreword" and whose slug is "foreword-ravenloft-revisited", is
    why `overrides` exists -- no derivation recovers words that are not in the
    title.
    """
    stripped = _CHAPTER_PREFIX.sub("", title)
    return _NON_SLUG.sub("-", _APOSTROPHES.sub("", stripped).lower()).strip("-")


def parse_toc(markdown: str) -> list[TocGroup]:
    """Read a book's table of contents into groups of chapter candidates.

    Only the part after the `## Contents` heading is considered when that
    heading is present, so the marketing blurb above it cannot mint chapters.
    """
    contents = _CONTENTS.search(markdown)
    body = markdown[contents.end():] if contents else markdown

    groups: list[TocGroup] = []
    headings = list(_TOC_HEADING.finditer(body))
    for i, match in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        children = [m.group(1).strip() for m in _TOC_ITEM.finditer(body[match.end():end])]
        groups.append(TocGroup(title=match.group(1).strip(), children=children))
    return groups


def is_missing_page(text: str) -> bool:
    """True when a slug resolved to D&D Beyond's 404 page rather than a chapter."""
    return PAGE_NOT_FOUND in text


def strip_block(text: str) -> Block:
    """Remove a readBook response's framing, keeping the rendered text exactly.

    The slices returned across a paginated read are exact substrings of one
    rendered chapter, so they concatenate back into it byte for byte -- but
    only if the framing is removed by matching the known strings rather than
    by stripping whitespace. A slice can legitimately begin or end with a
    newline, and losing it would shift every later offset.
    """
    lines = text.split("\n")
    body = "\n".join(lines[_HEADER_LINES:])

    # The header is followed by a single blank line in every response shape.
    if body.startswith("\n"):
        body = body[1:]

    body = _RANGE_NOTE.sub("", body, count=1)

    truncation = _TRUNCATION.search(body)
    if truncation is None:
        return Block(content=body, next_offset=None, total=None)
    return Block(
        content=body[: truncation.start()],
        next_offset=int(truncation.group(2)),
        total=int(truncation.group(3)),
    )


async def read_chapter(
    reader: Reader,
    book_slug: str,
    chapter_slug: str,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[str, int]:
    """Read one chapter to completion, paging until the server stops truncating.

    Returns the full markdown and the number of calls it cost. The server
    states the chapter's total character count in every truncation notice, so
    the reassembled text is checked against it; a mismatch means the page
    re-rendered differently between calls and the result is not trustworthy.
    """
    parts: list[str] = []
    offset = 0
    calls = 0
    total: int | None = None

    while True:
        block = strip_block(await reader(book_slug, chapter_slug, offset, page_size))
        calls += 1
        parts.append(block.content)
        if block.next_offset is None:
            break
        if block.next_offset <= offset:
            raise RuntimeError(
                f"{book_slug}/{chapter_slug}: offset did not advance past {offset}"
            )
        total = block.total
        offset = block.next_offset

    markdown = "".join(parts)
    if total is not None and len(markdown) != total:
        raise RuntimeError(
            f"{book_slug}/{chapter_slug}: reassembled {len(markdown)} characters, "
            f"server reported {total}"
        )
    return markdown, calls


def exit_code(manifest: dict) -> int:
    """0 only when every chapter in the table of contents actually landed.

    UNRESOLVED FAILS THE RUN, exactly as `failed` does, and for a stronger
    reason: `failed` means the page was found and the fetch broke, which is
    loud. Unresolved means the chapter was never located at all, so the book is
    quietly short one chapter and every count downstream still looks
    self-consistent. Keys from the Golden Vault sat in the graph missing its
    Introduction -- the chapter defining the Golden Vault itself, and the only
    place Meera Raheer or the rival-crew rules appear -- because this returned
    0 and the warning printed above it scrolled past.

    A named function rather than an expression inside `main` so it can be
    tested without a network or an argv.
    """
    return 1 if manifest["failed"] or manifest["unresolved"] else 0


def load_overrides(book_slug: str, path: Path | None = None) -> dict[str, str]:
    """Load title -> slug overrides for a book, if any are recorded."""
    source = path or SLUG_DIR / f"{slug_filename(book_slug)}.json"
    if not source.exists():
        return {}
    return json.loads(source.read_text())


def cached_record(out_dir: Path, slug: str) -> ChapterRecord | None:
    """Return the sidecar for an already-complete chapter, else None.

    The character count is re-checked against the file rather than trusted,
    so a half-written markdown file from a killed run is re-fetched instead
    of being silently accepted as the chapter.
    """
    sidecar = out_dir / f"{slug}.json"
    markdown = out_dir / f"{slug}.md"
    if not sidecar.exists() or not markdown.exists():
        return None
    try:
        data = json.loads(sidecar.read_text())
    except json.JSONDecodeError:
        return None
    if not data.get("complete"):
        return None
    if data.get("chars") != len(markdown.read_text()):
        return None
    return ChapterRecord(**data)


def write_chapter(out_dir: Path, record: ChapterRecord, markdown: str) -> None:
    """Write a chapter and its sidecar, markdown first.

    Order matters for resumability: the sidecar is the completeness claim, so
    it must not exist before the text it describes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{record.slug}.md").write_text(markdown)
    (out_dir / f"{record.slug}.json").write_text(json.dumps(asdict(record), indent=2) + "\n")


async def harvest(
    reader: Reader,
    book_slug: str,
    fetched_on: str,
    out_dir: Path,
    page_size: int = DEFAULT_PAGE_SIZE,
    overrides: dict[str, str] | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Walk a book's table of contents and cache every chapter it can resolve.

    A `###` group is tried as a chapter first. If its slug 404s, its bullet
    children are tried instead -- which is how "Appendices" yields six
    chapters and no page of its own. Groups that resolve to nothing are
    reported rather than skipped silently, because a missing chapter is
    exactly the kind of loss this corpus exists to avoid.
    """
    overrides = overrides or {}
    toc = parse_toc(await reader(book_slug, None, 0, page_size))
    log(f"table of contents: {len(toc)} groups")

    records: list[ChapterRecord] = []
    skipped: list[str] = []
    unresolved: list[str] = []
    aliased: list[dict] = []
    failed: list[dict] = []
    seen: set[str] = set()
    toc_calls = 1
    probe_calls = 0

    async def take(title: str) -> str:
        """Cache one chapter, returning what happened.

        `"duplicate"` deliberately does not count as resolving a group. Curse
        of Strahd's "Poster Map" entry lists a bullet called "Castle
        Ravenloft", which derives the slug of chapter 4 -- a real page, but
        not this group's page. Treating that as a resolution would report a
        group as harvested when nothing of it was.
        """
        nonlocal probe_calls
        slug = overrides.get(title) or derive_slug(title)
        if slug in seen:
            return "duplicate"
        cached = cached_record(out_dir, slug)
        if cached is not None:
            seen.add(slug)
            records.append(cached)
            skipped.append(slug)
            log(f"  {slug}: cached ({cached.chars} chars)")
            return "cached"
        try:
            markdown, calls = await read_chapter(reader, book_slug, slug, page_size)
        except Exception as err:  # noqa: BLE001 -- one bad chapter must not end the walk
            failed.append({"title": title, "slug": slug, "error": str(err)})
            log(f"  {slug}: FAILED ({err})")
            return "failed"
        if is_missing_page(markdown):
            probe_calls += calls
            return "missing"
        seen.add(slug)
        record = ChapterRecord(
            slug=slug,
            title=title,
            chars=len(markdown),
            calls=calls,
            fetched_on=fetched_on,
        )
        write_chapter(out_dir, record, markdown)
        records.append(record)
        log(f"  {slug}: {record.chars} chars in {calls} call(s)")
        return "new"

    for group in toc:
        if await take(group.title) != "missing":
            continue
        log(f"  {group.title!r} is not a page; trying its {len(group.children)} children")
        outcomes = {child: await take(child) for child in group.children}
        if any(outcome != "missing" and outcome != "duplicate" for outcome in outcomes.values()):
            continue
        unresolved.append(group.title)
        duplicates = [c for c, o in outcomes.items() if o == "duplicate"]
        if duplicates:
            aliased.append({"group": group.title, "children": duplicates})

    fetch_calls = sum(r.calls for r in records if r.slug not in skipped)
    return {
        "book_slug": book_slug,
        "fetched_on": fetched_on,
        "chapters": [asdict(r) for r in records],
        "chapter_count": len(records),
        "total_chars": sum(r.chars for r in records),
        "calls": toc_calls + fetch_calls + probe_calls,
        "skipped": skipped,
        "unresolved": unresolved,
        "aliased": aliased,
        "failed": failed,
    }


class MCPReader:
    """A `Reader` backed by one long-lived `dndbeyond` MCP session.

    One session per harvest, not one per chapter: the server drives a real
    browser, and paying its startup and D&D Beyond's login check 25 times over
    would dominate the run.
    """

    def __init__(self, command: str, args: list[str]) -> None:
        self._command = command
        self._args = args
        self._session = None
        self._stack = None

    async def __aenter__(self) -> "MCPReader":
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        params = StdioServerParameters(command=self._command, args=self._args)
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._stack is not None
        await self._stack.__aexit__(*exc)

    async def __call__(
        self, book_slug: str, chapter_slug: str | None, offset: int, limit: int
    ) -> str:
        assert self._session is not None, "MCPReader must be used as an async context manager"
        arguments: dict[str, object] = {"book_slug": book_slug, "offset": offset, "limit": limit}
        if chapter_slug:
            arguments["chapter_slug"] = chapter_slug
        result = await self._session.call_tool("ddb_read_book", arguments)
        text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
        if result.isError:
            raise RuntimeError(f"ddb_read_book failed for {book_slug}/{chapter_slug}: {text}")
        return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--book", default="dnd/cos", help="book slug, e.g. dnd/cos")
    parser.add_argument("--out", type=Path, default=None, help="cache directory")
    parser.add_argument(
        "--fetched-on",
        default=date.today().isoformat(),
        help="date recorded in every sidecar written by this run",
    )
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--slugs", type=Path, default=None, help="title -> slug override JSON")
    parser.add_argument("--server-command", default="node")
    parser.add_argument(
        "--server-args",
        nargs="+",
        default=["/Users/csinger/projects/ddb-mcp/dist/index.js"],
    )
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args(argv)

    out_dir = args.out or DEFAULT_ROOT / slug_filename(args.book).removeprefix("dnd-")
    overrides = load_overrides(args.book, args.slugs)

    async def run() -> dict:
        async with MCPReader(args.server_command, args.server_args) as reader:
            return await harvest(
                reader,
                args.book,
                fetched_on=args.fetched_on,
                out_dir=out_dir,
                page_size=args.page_size,
                overrides=overrides,
            )

    started = time.monotonic()
    manifest = asyncio.run(run())
    manifest["wall_clock_seconds"] = round(time.monotonic() - started, 1)

    path = args.manifest or out_dir / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(
        f"{manifest['chapter_count']} chapters, {manifest['total_chars']} chars, "
        f"{manifest['calls']} calls, {manifest['wall_clock_seconds']}s -> {out_dir}"
    )
    if manifest["failed"]:
        print(f"FAILED: {[f['slug'] for f in manifest['failed']]}", file=sys.stderr)
    if manifest["unresolved"]:
        print(f"UNRESOLVED: {manifest['unresolved']}", file=sys.stderr)
    return exit_code(manifest)


if __name__ == "__main__":
    raise SystemExit(main())
