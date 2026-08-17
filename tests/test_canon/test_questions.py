"""Turning a DM's question into search terms."""

from backend.canon.questions import content_terms, lucene_query


class TestContentTerms:
    def test_the_question_words_go_and_the_subject_stays(self):
        assert content_terms("Who is the old woman selling pastries?") == [
            "old",
            "woman",
            "selling",
            "pastries",
        ]

    def test_the_tables_own_furniture_goes_too(self):
        """`characters` and `party` appear in every question and describe none
        of them -- left in, they pull the introduction's advice sections ahead
        of any answer."""
        assert content_terms("What level should the characters be?") == ["level"]
        assert content_terms("Where should the party go next?") == ["next"]

    def test_a_repeated_word_is_counted_once(self):
        """A question saying `house` twice is not twice as much about houses,
        and Lucene would weight it as though it were."""
        assert content_terms("A house, and another house entirely") == [
            "house",
            "another",
            "entirely",
        ]

    def test_a_dice_expression_survives_the_length_rule(self):
        """The rule drops short words, and `d20` is two letters and a digit."""
        assert "d20" in content_terms("What do I roll on the d20 table?")

    def test_order_is_the_questions_own(self):
        assert content_terms("pastries and the old woman") == [
            "pastries",
            "old",
            "woman",
        ]

    def test_a_question_of_pure_scaffolding_yields_nothing(self):
        """An empty term list must be visible to the caller: an empty Lucene
        query is a syntax error, not an empty result set."""
        assert content_terms("What is it?") == []
        assert content_terms("") == []


class TestLuceneQuery:
    def test_terms_are_ored(self):
        """AND is how "the old woman selling pastries" returns nothing at all:
        a descriptive question rarely uses the book's vocabulary for every part
        of what it describes."""
        assert lucene_query(["old", "woman"]) == "old OR woman"

    def test_lucene_syntax_in_a_question_is_escaped_not_executed(self):
        """`E5f.` or a stray `~` would otherwise be parsed as a proximity or
        fuzzy search -- a different kind of guess, arrived at by accident."""
        assert lucene_query(["cat~2"]) == "cat\\~2"
        assert lucene_query(["a:b"]) == "a\\:b"
        assert lucene_query(["(x)"]) == "\\(x\\)"

    def test_a_backslash_is_escaped_before_what_follows_it(self):
        """Escaped first, or its own escape character re-escapes the next one."""
        assert lucene_query(["a\\b"]) == "a\\\\b"

    def test_an_empty_term_list_gives_an_empty_query(self):
        assert lucene_query([]) == ""
