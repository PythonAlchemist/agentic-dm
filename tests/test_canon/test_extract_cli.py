"""CLI plumbing. The extraction itself is tested in test_extract.py."""

import pytest

from backend.canon.models import Chapter
from backend.scripts.extract_canon import find_chapter


def chapter(title: str) -> Chapter:
    return Chapter(slug="s", title=title, start_page=1, end_page=2, markdown="x")


class TestFindChapter:
    def test_matches_on_a_prefix(self):
        chapters = [chapter("Chapter 3: The Village of Barovia"),
                    chapter("Chapter 4: Castle Ravenloft")]

        assert find_chapter(chapters, "Chapter 3").title.startswith("Chapter 3")

    def test_match_is_case_insensitive(self):
        chapters = [chapter("Chapter 3: The Village of Barovia")]

        assert find_chapter(chapters, "chapter 3") is chapters[0]

    def test_unknown_chapter_raises_with_the_available_titles(self):
        chapters = [chapter("Chapter 3: The Village of Barovia")]

        with pytest.raises(ValueError) as exc:
            find_chapter(chapters, "Chapter 9")
        assert "Chapter 3" in str(exc.value)

    def test_ambiguous_prefix_raises(self):
        chapters = [chapter("Chapter 1: Into the Mists"),
                    chapter("Chapter 10: The Ruins of Berez")]

        with pytest.raises(ValueError):
            find_chapter(chapters, "Chapter 1")
