#!/usr/bin/env python3
"""Put a book's chapters back in the order its manifest gives them.

    uv run python -m backend.scripts.reindex_chapters --book kftgv
    uv run python -m backend.scripts.reindex_chapters --book kftgv --apply

WHY THIS EXISTS. `write_canon` takes a chapter's index from its position in the
corpus manifest, one chapter at a time. That is right at the moment of writing
and goes stale the moment the manifest changes: a chapter written when it was
first in the list keeps index 0 after something is inserted above it, and now
two chapters claim the same position.

WHAT IT LOOKED LIKE. kftgv had `introduction-a-collection-of-heists` and
`the-murkmire-malevolence` both at index 0, so the running order -- which sorts
by `(chapter.index, section.index)` -- ZIPPED them, alternating the two chapters
row by row for the whole book. It reads as a shuffled table of contents, and it
is the kind of defect that looks like a UI bug from every angle except this one.

IT REWRITES ONLY THE INDEX, on the `:Chapter` and on its `HAS_CHAPTER` edge,
both of which `writer.py` sets together. No section, entity, mention or edge is
touched: this is the book's own order being restored, not its content.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.database import neo4j_session

STORED = """
MATCH (:Book {slug:$book})-[h:HAS_CHAPTER]->(c:Chapter)
RETURN c.slug AS slug, c.index AS index ORDER BY c.index, c.slug
"""

REINDEX = """
MATCH (:Book {slug:$book})-[h:HAS_CHAPTER]->(c:Chapter {slug:$slug})
SET c.index = $index, h.index = $index
RETURN count(c) AS n
"""


def manifest_order(book: str, corpus: str) -> list[str]:
    """The book's own order, from the corpus manifest `write_canon` reads."""
    from backend.scripts.extract_canon import load_chapters

    return [c.slug for c in load_chapters(corpus, book_slug=book)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", required=True)
    parser.add_argument("--corpus", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    corpus = args.corpus or args.book

    try:
        order = manifest_order(args.book, corpus)
    except Exception as failed:  # noqa: BLE001 -- the message is the useful half
        print(f"could not read the {corpus!r} manifest: {failed}", file=sys.stderr)
        return 1
    wanted = {slug: i for i, slug in enumerate(order)}

    with neo4j_session() as session:
        stored = [dict(r) for r in session.run(STORED, {"book": args.book})]
        if not stored:
            print(f"no chapters for {args.book!r}", file=sys.stderr)
            return 1

        moved, missing = [], []
        for row in stored:
            if row["slug"] not in wanted:
                missing.append(row["slug"])
                continue
            if row["index"] != wanted[row["slug"]]:
                moved.append((row["slug"], row["index"], wanted[row["slug"]]))

        duplicates = len(stored) - len({r["index"] for r in stored})
        print(f"  chapters        {len(stored)}")
        print(f"  sharing an index {duplicates}")
        print(f"  out of place    {len(moved)}")
        for slug, was, now in moved:
            print(f"    {slug:44} {was} -> {now}")
        if missing:
            # COUNTED, NEVER SILENT: a chapter in the graph and not in the
            # manifest is a real question, not something to skip past.
            print(f"  in the graph but not the manifest: {missing}")

        if not args.apply:
            print("\nnothing written -- pass --apply")
            return 0

        for slug, _was, now in moved:
            session.execute_write(lambda tx, s=slug, i=now: tx.run(
                REINDEX, {"book": args.book, "slug": s, "index": i}).consume())
        print(f"\nreindexed {len(moved)} chapters of {args.book!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
