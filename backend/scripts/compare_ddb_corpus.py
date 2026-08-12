#!/usr/bin/env python3
"""Compare the D&D Beyond corpus against the vision transcription it replaces.

Nothing here writes to Neo4j, calls an LLM, or touches the network: both
sources are already on disk. The point is to decide whether the new corpus can
be trusted before anything is re-pointed at it, so every check is a count that
can be argued about rather than a summary that cannot.

Two questions the comparison answers:

1. Do the sources agree on the book's keyed areas -- the `K18`, `E5g`, `N3`
   labels the adventure hangs its rooms on? A disagreement means one of them
   invented or lost a room.
2. Does D&D Beyond's heading *depth* encode containment -- is `K18a` nested
   under `K18`? The transcription's depths were noise, which is why the
   pipeline derives containment from the key strings instead. If the
   publisher's depths are meaningful, that derivation could stop depending on
   a key convention that only this book uses.
"""

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

DEFAULT_DDB_DIR = Path("data/ddb/cos")

# The task's rule: a key is a letter, digits, and an optional single-letter
# sub-area suffix. The suffix is matched case-insensitively because the
# transcription sometimes shouted it ("K74G") where D&D Beyond writes "K74g".
KEY = re.compile(r"^(?P<stem>[A-Za-z]\d+)(?P<suffix>[A-Za-z])?\.")

HEADING = re.compile(r"^(#{1,6})\s+(?!#)(.+?)\s*$", re.MULTILINE)

# Chapter titles differ in wording between sources ("Chapter 3: The Village of
# Barovia" vs "The Village of Barovia"), so they are matched on the slug-ish
# tail after any "Chapter N:" / "Appendix X:" prefix is normalised away.
_TITLE_PREFIX = re.compile(r"^\s*(chapter\s+\d+|ch\.?\s*\d+)\s*[:.]\s*", re.IGNORECASE)
_APPENDIX = re.compile(r"^\s*appendix\s+([a-z])\b\s*[:.]?\s*", re.IGNORECASE)
_NON_SLUG = re.compile(r"[^a-z0-9]+")

# Two chapters the sources name differently while covering the same pages.
# Both were checked by content, not by guessing at the titles:
#   * D&D Beyond's h1 is bare "Foreword" where the print book's is "Foreword:
#     Ravenloft Revisited" -- D&D Beyond's own slug still spells it out
#     ("foreword-ravenloft-revisited"), which is how the pair was confirmed.
#   * "Front Matter" is what the transcription calls the pages D&D Beyond
#     serves as "Credits"; both contain the "Lead Designer:" credit block.
ALIASES = {
    "foreword-ravenloft-revisited": "foreword",
    "front-matter": "credits",
}


def match_key(title: str) -> tuple[str, str] | None:
    """Return (stem, normalised suffix) for a keyed heading, else None."""
    m = KEY.match(title.strip())
    if m is None:
        return None
    return m.group("stem").upper(), (m.group("suffix") or "").lower()


def headings(markdown: str) -> list[tuple[int, str]]:
    """Every ATX heading as (depth, text)."""
    return [(len(m.group(1)), m.group(2).strip()) for m in HEADING.finditer(markdown)]


def normalise_title(title: str) -> str:
    """Collapse a chapter title to something both sources spell the same way."""
    appendix = _APPENDIX.match(title)
    if appendix:
        return f"appendix-{appendix.group(1).lower()}"
    stripped = _TITLE_PREFIX.sub("", title)
    key = _NON_SLUG.sub("-", stripped.lower().replace("’", "").replace("'", "")).strip("-")
    return ALIASES.get(key, key)


@dataclass
class Census:
    title: str
    chars: int
    keys: list[tuple[str, str]]
    depths: Counter
    upper_suffixes: int

    @property
    def distinct_keys(self) -> set[str]:
        return {stem + suffix for stem, suffix in self.keys}


def census(title: str, markdown: str) -> Census:
    heads = headings(markdown)
    keys = [k for _, text in heads if (k := match_key(text)) is not None]
    # The book prints sub-area suffixes lowercase ("K74g"). A count above zero
    # is a defect in whichever source reports it, not a difference of style.
    upper = sum(
        1
        for _, text in heads
        if (m := KEY.match(text.strip())) and (m.group("suffix") or "").isupper()
    )
    return Census(
        title=title,
        chars=len(markdown),
        keys=keys,
        depths=Counter(depth for depth, _ in heads),
        upper_suffixes=upper,
    )


def load_ddb(ddb_dir: Path) -> dict[str, Census]:
    manifest = json.loads((ddb_dir / "manifest.json").read_text())
    out: dict[str, Census] = {}
    for chapter in manifest["chapters"]:
        markdown = (ddb_dir / f"{chapter['slug']}.md").read_text()
        out[normalise_title(chapter["title"])] = census(chapter["title"], markdown)
    return out


def load_transcription() -> dict[str, Census]:
    from backend.scripts.extract_canon import load_chapters

    return {
        normalise_title(c.title): census(c.title, c.markdown) for c in load_chapters()
    }


def containment_report(chapters: dict[str, Census], ddb_dir: Path) -> dict:
    """Does a sub-area's heading sit deeper than its parent area's?

    A sub-area is a key with a letter suffix (`K18a`) whose stem (`K18`) also
    appears as a heading in the same chapter. If depth encoded containment,
    every such pair would have child depth > parent depth. If the structure is
    flat, they are equal.
    """
    deeper = same = shallower = 0
    orphan = 0
    pairs: list[tuple[str, int, int]] = []

    manifest = json.loads((ddb_dir / "manifest.json").read_text())
    for chapter in manifest["chapters"]:
        markdown = (ddb_dir / f"{chapter['slug']}.md").read_text()
        depth_of: dict[str, int] = {}
        for depth, text in headings(markdown):
            key = match_key(text)
            if key is not None:
                depth_of.setdefault(key[0] + key[1], depth)
        for label, depth in depth_of.items():
            if not label[-1].islower():
                continue
            parent = label[:-1]
            if parent not in depth_of:
                orphan += 1
                continue
            pairs.append((label, depth_of[parent], depth))
            if depth > depth_of[parent]:
                deeper += 1
            elif depth == depth_of[parent]:
                same += 1
            else:
                shallower += 1

    # The other containment claim worth testing: does an area's own body sit
    # under it, i.e. does a non-keyed heading that follows a keyed one go
    # deeper? "### K15. Chapel" then "### Treasure" would be flat.
    follower_deeper = follower_same = follower_shallower = 0
    for chapter in manifest["chapters"]:
        markdown = (ddb_dir / f"{chapter['slug']}.md").read_text()
        current: int | None = None
        for depth, text in headings(markdown):
            if match_key(text) is not None:
                current = depth
                continue
            if current is None:
                continue
            if depth > current:
                follower_deeper += 1
            elif depth == current:
                follower_same += 1
            else:
                follower_shallower += 1
                current = None

    return {
        "subarea_pairs": len(pairs),
        "subarea_deeper_than_parent": deeper,
        "subarea_same_depth_as_parent": same,
        "subarea_shallower_than_parent": shallower,
        "subarea_without_parent_heading": orphan,
        "unkeyed_after_keyed_deeper": follower_deeper,
        "unkeyed_after_keyed_same": follower_same,
        "unkeyed_after_keyed_shallower": follower_shallower,
        "examples": pairs[:10],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ddb-dir", type=Path, default=DEFAULT_DDB_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--table", action="store_true", help="print a markdown comparison table")
    args = parser.parse_args(argv)

    ddb = load_ddb(args.ddb_dir)
    old = load_transcription()

    rows = []
    for key in sorted(set(ddb) | set(old)):
        d, o = ddb.get(key), old.get(key)
        rows.append(
            {
                "chapter": key,
                "ddb_title": d.title if d else None,
                "old_title": o.title if o else None,
                "ddb_chars": d.chars if d else 0,
                "old_chars": o.chars if o else 0,
                "ddb_keys": len(d.distinct_keys) if d else 0,
                "old_keys": len(o.distinct_keys) if o else 0,
                "only_in_ddb": sorted(d.distinct_keys - o.distinct_keys) if d and o else [],
                "only_in_old": sorted(o.distinct_keys - d.distinct_keys) if d and o else [],
                "ddb_depths": dict(sorted(d.depths.items())) if d else {},
                "old_depths": dict(sorted(o.depths.items())) if o else {},
                "ddb_upper_suffixes": d.upper_suffixes if d else 0,
                "old_upper_suffixes": o.upper_suffixes if o else 0,
            }
        )

    report = {
        "ddb_chapters": len(ddb),
        "old_chapters": len(old),
        "ddb_total_chars": sum(c.chars for c in ddb.values()),
        "old_total_chars": sum(c.chars for c in old.values()),
        "missing_from_ddb": sorted(set(old) - set(ddb)),
        "missing_from_old": sorted(set(ddb) - set(old)),
        "rows": rows,
        "containment": containment_report(ddb, args.ddb_dir),
    }

    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n")
    if args.table:
        print_table(report)
    elif not args.out:
        print(json.dumps(report, indent=2))
    return 0


def _depths(counts: dict) -> str:
    return " ".join(f"h{k}:{v}" for k, v in counts.items()) or "-"


def print_table(report: dict) -> None:
    """Print the per-chapter comparison as a markdown table."""
    print(
        "| chapter | keys DDB/old | chars DDB/old | headings DDB | headings old "
        "| UPPER suffix DDB/old |"
    )
    print("| --- | --- | --- | --- | --- | --- |")
    for row in report["rows"]:
        keys = f"{row['ddb_keys']}/{row['old_keys']}"
        if row["only_in_ddb"] or row["only_in_old"]:
            keys += f" (+{row['only_in_ddb']} -{row['only_in_old']})"
        print(
            f"| {row['chapter']} | {keys} | {row['ddb_chars']}/{row['old_chars']} "
            f"| {_depths(row['ddb_depths'])} | {_depths(row['old_depths'])} "
            f"| {row['ddb_upper_suffixes']}/{row['old_upper_suffixes']} |"
        )
    print()
    print(f"chapters: DDB {report['ddb_chapters']}, transcription {report['old_chapters']}")
    print(f"chars:    DDB {report['ddb_total_chars']}, transcription {report['old_total_chars']}")
    print(f"missing from DDB: {report['missing_from_ddb'] or 'none'}")
    print(f"missing from transcription: {report['missing_from_old'] or 'none'}")
    containment = {k: v for k, v in report["containment"].items() if k != "examples"}
    print(f"containment: {json.dumps(containment)}")


if __name__ == "__main__":
    raise SystemExit(main())
