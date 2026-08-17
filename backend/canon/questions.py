"""Turn a DM's question into search terms, by stripping what every question says.

Only used by the TEXT FALLBACK. A question that names something the graph knows
never reaches here -- resolution through `:Alias` is a fact, and this module
produces a guess. Keeping the two apart is what lets a miss be diagnosed as
"named nothing" rather than "ranked badly".

WHY STRIP AT ALL, when Lucene already has a stopword list. Because a DM's
question carries a second layer of noise that no general analyzer knows about:
the table's own scaffolding. "What do I roll for", "how do the characters",
"should the party" are pure form -- they appear in every question and describe
none of them. Left in, `characters` and `party` are content words that match the
introduction's advice sections ahead of the answer.

The lists are short, explicit, and English. That is a limitation and it is
written down rather than hidden behind a library: this book is in English, and a
rule a reader can check beats a rule that is merely general.
"""

from __future__ import annotations

import re

#: Interrogatives and the grammar that carries them. Removed as WORDS.
_QUESTION_WORDS = frozenset(
    """
    who what when where why which how whose whom
    is are was were be been being am
    do does did doing done
    can could shall should will would may might must
    a an the this that these those there here
    i me my we us our you your it its they them their
    of in on at to for from by with about into onto over under
    and or but if then than as so
    """.split()
)

#: The table's own furniture. A DM says these about every scene, so they carry
#: no information about WHICH scene -- and `characters` in particular pulls the
#: introduction's advice sections ahead of any answer.
_TABLE_WORDS = frozenset(
    """
    character characters pc pcs party player players adventurer adventurers
    dm gm campaign session game adventure
    """.split()
)

#: A word this short is noise in a Lucene query -- and `d20` must survive, so
#: the rule is on LETTERS rather than on length alone.
_MIN_LENGTH = 3

_WORD = re.compile(r"[\w’']+")


def content_terms(question: str) -> list[str]:
    """The words in a question that say what it is ABOUT, in their original order.

    Order is kept because it costs nothing and makes the terms readable in a log
    beside the question they came from. Duplicates are dropped: a question
    saying "house" twice is not twice as much about houses, and Lucene would
    weight it as though it were.
    """
    seen: dict[str, None] = {}
    for match in _WORD.finditer(question.lower()):
        word = match.group(0).strip("'’")
        if not word or word in _QUESTION_WORDS or word in _TABLE_WORDS:
            continue
        if len(word) < _MIN_LENGTH and not any(ch.isdigit() for ch in word):
            continue
        seen.setdefault(word, None)
    return list(seen)


def lucene_query(terms: list[str]) -> str:
    """A Lucene OR query over the terms, each one escaped.

    ESCAPED, not merely quoted. A question containing `E5f.` or a stray `~`
    would otherwise be parsed as Lucene syntax -- at best a syntax error thrown
    back through the driver, at worst a fuzzy or proximity search nobody asked
    for. This module exists to produce a guess; it must not also produce a
    DIFFERENT KIND of guess by accident.

    OR rather than AND, because a descriptive question rarely uses the book's
    own vocabulary for every part of the thing it describes. AND is how "the old
    woman selling pastries" returns nothing at all.
    """
    return " OR ".join(_escape(term) for term in terms if term)


#: Lucene's own reserved characters. `\\` is first so its own escaping does not
#: re-escape what follows.
_RESERVED = ["\\", "+", "-", "&", "|", "!", "(", ")", "{", "}", "[", "]",
             "^", '"', "~", "*", "?", ":", "/"]


def _escape(term: str) -> str:
    for char in _RESERVED:
        term = term.replace(char, "\\" + char)
    return term
