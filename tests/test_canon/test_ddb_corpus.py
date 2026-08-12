"""Reading chapters from the harvested D&D Beyond cache.

`load_chapters` used to rebuild chapters from the vision transcription: render
`data/cos.pdf` to page images, look each page up in the transcript cache,
reassemble. That cost money per run, served exactly one book, and produced
markdown whose heading levels were noise. The D&D Beyond harvest writes one
markdown file plus one JSON sidecar per chapter, so reading it is a directory
walk with no model in the loop -- and the same reader serves every book the user
owns.

The transcription stays reachable behind `--corpus transcription`. Legs A and B
of the measurement need it, and it is cheap insurance while the new path is
young.

No book text is committed. These tests build their own corpus in a tmpdir.
"""

import json

import pytest

from backend.scripts.extract_canon import build_parser, load_chapters, report_structure


def write_corpus(root, chapters: list[tuple[str, str, str]]) -> None:
    """`(slug, manifest title, markdown)` -> a harvest-shaped cache on disk."""
    book = root / "cos"
    book.mkdir(parents=True)
    for slug, title, markdown in chapters:
        (book / f"{slug}.md").write_text(markdown)
        (book / f"{slug}.json").write_text(
            json.dumps({"slug": slug, "title": title, "chars": len(markdown),
                        "calls": 1, "fetched_on": "2026-08-11", "complete": True})
        )
    (book / "manifest.json").write_text(
        json.dumps({
            "book_slug": "dnd/cos",
            "fetched_on": "2026-08-11",
            "chapters": [
                {"slug": slug, "title": title, "chars": len(md), "calls": 1,
                 "fetched_on": "2026-08-11", "complete": True}
                for slug, title, md in chapters
            ],
        })
    )


def _filler(tokens: int) -> str:
    return " ".join(["word"] * tokens)


# The village chapter carries enough prose for the derived area depth to land on
# h3 rather than on the whole chapter: its two areas fit one extraction pass and
# the `## Areas of the Village` divider above them does not. A three-line chapter
# would derive h1 and be a fixture about nothing.
CORPUS = [
    ("introduction", "Introduction", "# Introduction\n\nHow to run this.\n"),
    ("the-village-of-barovia", "Ch. 3: The Village of Barovia",
     "# Chapter 3: The Village of Barovia\n\nThe saddest place.\n\n"
     "## Areas of the Village\n\n"
     f"### E1. Bildrath's Mercantile\n\nOverpriced. {_filler(600)}\n\n"
     f"### E2. Blood of the Vine Tavern\n\nShoddy. {_filler(600)}\n"),
    ("castle-ravenloft", "Ch. 4: Castle Ravenloft",
     "# Chapter 4: Castle Ravenloft\n\nThe castle.\n"),
]


class TestLoadDdbChapters:
    def test_reads_every_chapter_in_the_cache(self, tmp_path):
        write_corpus(tmp_path, CORPUS)

        chapters = load_chapters(corpus="ddb", ddb_root=tmp_path)

        assert [c.slug for c in chapters] == [
            "introduction", "the-village-of-barovia", "castle-ravenloft"
        ]

    def test_keeps_the_manifest_order(self, tmp_path):
        """Chapter order is the book's, not the filesystem's. Alphabetically
        `castle-ravenloft` sorts first, and a corpus that opened on chapter 4
        would silently mis-order every consumer that walks chapters in sequence.
        """
        write_corpus(tmp_path, CORPUS)

        chapters = load_chapters(corpus="ddb", ddb_root=tmp_path)

        assert [c.slug for c in chapters][1] == "the-village-of-barovia"

    def test_the_title_comes_from_the_documents_own_h1(self, tmp_path):
        """The manifest carries D&D Beyond's table-of-contents label, "Ch. 3:
        The Village of Barovia". The page itself is headed "Chapter 3: ...",
        which is what `find_chapter("Chapter 3")` matches and what
        `chapter_place` strips to get "The Village of Barovia". Taking the
        manifest label instead would leave the chapter place as the literal
        string "Ch. 3: The Village of Barovia" and break every derived edge."""
        write_corpus(tmp_path, CORPUS)

        chapters = load_chapters(corpus="ddb", ddb_root=tmp_path)

        assert chapters[1].title == "Chapter 3: The Village of Barovia"

    def test_falls_back_to_the_manifest_title_when_a_file_has_no_h1(self, tmp_path):
        write_corpus(tmp_path, [("credits", "Credits", "Some names.\n")])

        chapters = load_chapters(corpus="ddb", ddb_root=tmp_path)

        assert chapters[0].title == "Credits"

    def test_the_markdown_arrives_intact(self, tmp_path):
        write_corpus(tmp_path, CORPUS)

        chapters = load_chapters(corpus="ddb", ddb_root=tmp_path)

        assert "E1. Bildrath's Mercantile" in chapters[1].markdown

    def test_a_missing_cache_says_how_to_build_it(self, tmp_path):
        """The corpus is gitignored, so a fresh clone has none of it. The error
        has to name the harvester rather than surface as a bare FileNotFound."""
        with pytest.raises(FileNotFoundError, match="harvest_ddb"):
            load_chapters(corpus="ddb", ddb_root=tmp_path / "absent")

    def test_an_unknown_corpus_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="corpus"):
            load_chapters(corpus="nonsense", ddb_root=tmp_path)


class TestCliDefaults:
    def test_the_corpus_defaults_to_ddb(self):
        args = build_parser().parse_args(["Chapter 3"])

        assert args.corpus == "ddb"

    def test_the_splitter_defaults_to_depth(self):
        args = build_parser().parse_args(["Chapter 3"])

        assert args.splitter == "depth"

    def test_the_transcription_is_still_reachable(self):
        args = build_parser().parse_args(["Chapter 3", "--corpus", "transcription"])

        assert args.corpus == "transcription"

    def test_the_key_splitter_is_still_reachable(self):
        """Leg B of the measurement is DDB text through the OLD splitter, and
        without it a corpus effect cannot be told from a splitter effect."""
        args = build_parser().parse_args(["Chapter 3", "--splitter", "key"])

        assert args.splitter == "key"

    def test_an_unknown_corpus_is_rejected_at_the_command_line(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["Chapter 3", "--corpus", "nonsense"])


class TestStructureReport:
    """The free diagnostic. The area depth is derived per chapter, so evidence
    from chapter 3 is not evidence about the book -- this walks all 25 without a
    model in the loop, which is what makes a one-level-wrong derivation visible
    before a paid run rather than after one.
    """

    def test_reports_a_row_per_chapter(self, tmp_path):
        write_corpus(tmp_path, CORPUS)

        rows = report_structure(load_chapters(corpus="ddb", ddb_root=tmp_path))

        assert [r["slug"] for r in rows] == [c[0] for c in CORPUS]

    def test_carries_the_derived_depth_and_the_keyed_section_count(self, tmp_path):
        write_corpus(tmp_path, CORPUS)

        rows = {r["slug"]: r for r in report_structure(
            load_chapters(corpus="ddb", ddb_root=tmp_path))}

        assert rows["the-village-of-barovia"]["area_depth"] == 3
        assert rows["the-village-of-barovia"]["keyed_sections"] == 2
        assert rows["introduction"]["keyed_sections"] == 0

    def test_a_chapter_where_no_depth_qualified_is_flagged(self, tmp_path):
        """Foreword and Credits are single-h1 chapters whose one span exceeds
        the budget with nothing to cut at. Silence there would be the rule
        pretending it had an answer."""
        write_corpus(tmp_path, [("credits", "Credits", "# Credits\n\n" + "word " * 4000)])

        rows = report_structure(load_chapters(corpus="ddb", ddb_root=tmp_path))

        assert rows[0]["qualified"] is False
        assert rows[0]["unsplittable"] == 1
