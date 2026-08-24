"""How far a name reaches inside a book.

Pure and exact: the scoping rule is the whole of the decision, so it is stated
here as tests rather than inferred from a graph afterwards.
"""

from pathlib import Path

from backend.canon.books import LEGACY, BookScheme, load


class TestACampaignIsOneWorld:
    """Curse of Strahd names Madam Eva in the introduction and in chapter 3,
    and she is one woman both times."""

    def test_an_unkeyed_name_is_global_to_the_book(self):
        campaign = BookScheme(prefix="cos")
        assert not campaign.scopes_to_chapter("Madam Eva")

    def test_the_legacy_scheme_is_a_campaign(self):
        """Every id written before books were a parameter meant this."""
        assert LEGACY.prefix == "cos"
        assert not LEGACY.anthology


class TestAnAnthologyIsManyWorlds:
    """Thirteen heists sharing no continuity. A guard in heist one and a guard
    in heist seven are two people."""

    def test_an_unkeyed_name_belongs_to_its_chapter(self):
        anthology = BookScheme(prefix="kftgv", anthology=True)
        assert anthology.scopes_to_chapter("Guard")

    def test_an_allowlisted_name_stays_book_wide(self):
        """The Golden Vault is one organisation across all thirteen, named 88
        times in 14 chapters. The rule with no exception would make it
        thirteen organisations."""
        anthology = BookScheme(
            prefix="kftgv", anthology=True, global_names=frozenset({"the golden vault"})
        )
        assert not anthology.scopes_to_chapter("The Golden Vault")
        assert anthology.scopes_to_chapter("Guard")

    def test_the_allowlist_names_a_thing_not_a_spelling(self):
        """The bug this had, and it did the opposite of its job.

        Written exact, `The Golden Vault` made only the entity spelled that way
        global and left every `Golden Vault` to be scoped per chapter. The one
        line meant to keep the organisation whole shattered it into thirteen,
        one per adventure, beside a fourteenth holding the mentions that
        happened to use the article.
        """
        anthology = BookScheme(
            prefix="kftgv", anthology=True, global_names=frozenset({"golden vault"})
        )
        for spelling in ("The Golden Vault", "the Golden Vault", "Golden Vault"):
            assert not anthology.scopes_to_chapter(spelling), spelling

    def test_it_still_refuses_a_different_thing(self):
        """`the vault` is Vidorant's vault in one adventure and a keyed room in
        another. Article-stripping must not turn the allowlist into a prefix
        match."""
        anthology = BookScheme(
            prefix="kftgv", anthology=True, global_names=frozenset({"golden vault"})
        )
        assert anthology.scopes_to_chapter("the vault")
        assert anthology.scopes_to_chapter("Vault")

    def test_the_allowlist_ignores_case(self):
        """The book heads `The Golden Vault` and writes it lowercase
        mid-sentence; a hand-authored list cannot chase that."""
        anthology = BookScheme(
            prefix="kftgv", anthology=True, global_names=frozenset({"the golden vault"})
        )
        assert anthology.is_global("the golden vault")
        assert anthology.is_global("  The Golden Vault  ")

    def test_an_allowlist_on_a_campaign_changes_nothing(self):
        """Everything is already global there, so the exception has nothing to
        except."""
        campaign = BookScheme(prefix="cos", global_names=frozenset({"madam eva"}))
        assert not campaign.scopes_to_chapter("Madam Eva")
        assert not campaign.scopes_to_chapter("Anybody Else")


class TestReadingOneFromDisk:
    def test_it_reads_the_prefix_and_the_rule(self, tmp_path: Path):
        path = tmp_path / "book.yaml"
        path.write_text(
            "prefix: kftgv\nanthology: true\nglobal_names:\n  - The Golden Vault\n"
        )
        scheme = load(path)
        assert scheme.prefix == "kftgv"
        assert scheme.anthology is True
        assert scheme.is_global("the golden vault")

    def test_a_book_with_no_rule_stated_is_a_campaign(self):
        """Silence means the old behaviour, so an existing book's file needs no
        field it never had."""
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write("prefix: cos\n")
            path = Path(handle.name)
        scheme = load(path)
        assert scheme.anthology is False
        assert scheme.global_names == frozenset()


class TestMintingUnderAScheme:
    """The rule where it lands: in the id."""

    @staticmethod
    def _mint(*args, **kwargs):
        from backend.canon.writer import mint_id

        return mint_id(*args, **kwargs)

    def test_the_prefix_comes_from_the_book(self):
        """Two books in one graph collide unless it does. Every id was `cos:`
        whatever book wrote it, until this."""
        assert self._mint(
            "the-murkmire-malevolence", "Varkenbluff Museum",
            scheme=BookScheme(prefix="kftgv"),
        ).startswith("kftgv:")

    def test_a_campaign_mints_an_unkeyed_name_globally(self):
        assert self._mint("chapter-3", "Madam Eva", scheme=LEGACY) == "cos:madam-eva"

    def test_an_anthology_mints_it_under_its_chapter(self):
        """A guard in heist one is not the guard in heist seven."""
        anthology = BookScheme(prefix="kftgv", anthology=True)
        assert self._mint("prisoner-13", "Guard", scheme=anthology) == (
            "kftgv:prisoner-13:guard"
        )

    def test_two_anthology_chapters_mint_different_ids_for_one_name(self):
        """The whole point. Under the campaign rule these are one node."""
        anthology = BookScheme(prefix="kftgv", anthology=True)
        first = self._mint("prisoner-13", "Guard", scheme=anthology)
        second = self._mint("fire-and-darkness", "Guard", scheme=anthology)
        assert first != second

    def test_an_allowlisted_name_is_one_node_across_the_anthology(self):
        """The Golden Vault is named 88 times in 14 chapters and is the only
        thing connecting them."""
        anthology = BookScheme(
            prefix="kftgv", anthology=True, global_names=frozenset({"the golden vault"})
        )
        first = self._mint("prisoner-13", "The Golden Vault", scheme=anthology)
        second = self._mint("heart-of-ashes", "The Golden Vault", scheme=anthology)
        assert first == second == "kftgv:the-golden-vault"

    def test_a_keyed_place_is_unaffected_by_the_scoping_rule(self):
        """It already resolved to (book, chapter, key) and has done since long
        before books were a parameter."""
        for scheme in (BookScheme(prefix="kftgv"), BookScheme(prefix="kftgv", anthology=True)):
            assert self._mint("prisoner-13", "Cell Block", "4a", scheme=scheme) == (
                "kftgv:prisoner-13:4a-cell-block"
            )

    def test_the_section_id_carries_the_prefix_too(self):
        """A section under `cos:` in a KFTGV graph would attach that book's
        prose to the wrong book."""
        from backend.canon.spine import section_id

        assert section_id("prisoner-13", 4, scheme=BookScheme(prefix="kftgv")) == (
            "kftgv:prisoner-13#4"
        )
