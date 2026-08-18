"""Which sections answer a question but are not listed as its gold?

    uv run python -m backend.scripts.audit_questions
    uv run python -m backend.scripts.audit_questions --only q22 q25

Costs nothing: no model runs, and the whole thing is a heading comparison.

THE CHECK THAT WAS NEVER RUN. Auditing the question set once, I asked of every
gold "does this section answer its question?" and all 46 answered yes -- and
that is the wrong question asked alone. q22 and q25 both had a correct gold
while the book ALSO answered them somewhere else, so retrieval returning the
OTHER correct section was scored a miss and counted as evidence that ranking
needed work. For q25 the unlisted section was the BETTER one: gold pointed at
a random-encounter entry, and the passage retrieval kept returning opens
"Rahadin, the dusk elf chamberlain of Castle Ravenloft".

WIDENING A GOLD RAISES THE SCORE, which makes this the one kind of edit that
can quietly become tuning the ruler. Two things hold that line. This script
only ever prints a READING QUEUE -- it never edits anything and has no notion
of whether retrieval found a section. And a widened gold has to carry its
reason in the file beside it, so the case survives being read back by somebody
who did not make it.

HOW A CANDIDATE IS FOUND. The `note` states the hand-checked answer, so its
distinctive proper nouns are that answer's fingerprint. Matching them against
section TEXT flags a third of the book -- `Castle Ravenloft` is everywhere --
so the match is against the HEADING, on the reasoning that a section headed
with a name is about that name rather than merely mentioning it. Both real
cases were found this way. It is still generous: `House Occupants`, `S2.
Gatehouse` and every `N9x. Vistani …` wagon come along for the ride, and the
queue is meant to be read rather than believed.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

DEFAULT_QUESTIONS = Path("evals/canon-questions.yaml")

#: Capitalised words that are not evidence of a name -- sentence openers,
#: game-mechanical vocabulary, and the handful of place names so common that a
#: fingerprint containing one matches the entire corpus.
_STOP = frozenset(
    """The A An He She It They His Her Their This That There Two Three Every
    Each If When No Not DC Names Adopted Strength Charisma Wisdom Intelligence
    Check Roll Chapter Use One Both In On At Barovia Barovian Strahd Castle
    Ravenloft Vallaki Player Handbook Monster Manual""".split()
)

SECTIONS = """
MATCH (c:Chapter {plane:$plane})-[:HAS_SECTION]->(s:Section)
RETURN s.id AS id, s.heading AS heading, substring(s.text, 0, 200) AS head
"""


def fingerprint(note: str, question: str) -> list[str]:
    """The note's distinctive names, minus anything the question already says.

    A term the question itself uses cannot discriminate: every section about
    Strahd contains `Strahd`, so keeping it would flag the whole book for every
    question that names him.
    """
    asked = set(re.findall(r"[A-Za-z']+", question.lower()))
    return sorted(
        {
            word
            for word in re.findall(r"\b[A-Z][A-Za-z'’-]{2,}\b", note)
            if word not in _STOP and word.lower() not in asked
        }
    )


def rivals(question: dict, sections: list[dict], by_id: dict[str, dict]) -> list[dict]:
    """Sections worth reading against this question's gold.

    Two ways in, and the second is what q25 needed: a section sharing a gold
    section's EXACT heading. The book heads two different sections `Rahadin`,
    one the encounter and one the NPC entry, and no fingerprint distinguishes
    them because the name is identical.
    """
    gold = set(question["sections"])
    terms = fingerprint(question.get("note", ""), question["question"])
    gold_headings = {by_id[g]["heading"] for g in gold if g in by_id}

    found: dict[str, dict] = {}
    for section in sections:
        if section["id"] in gold:
            continue
        heading = (section["heading"] or "").lower()
        if any(term.lower() in heading for term in terms) or (
            section["heading"] in gold_headings
        ):
            found[section["id"]] = section
    return list(found.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--only", nargs="*", help="question ids to audit")
    args = parser.parse_args()

    from backend.canon.retrieval import CanonRetriever

    questions = yaml.safe_load(args.questions.read_text())["questions"]
    if args.only:
        questions = [q for q in questions if q["id"] in set(args.only)]

    retriever = CanonRetriever()
    with retriever._session() as session:
        sections = retriever._rows(session, SECTIONS)
    by_id = {s["id"]: s for s in sections}

    queued = 0
    for question in questions:
        found = rivals(question, sections, by_id)
        if not found:
            continue
        queued += len(found)
        print(f"\n{question['id']:<5} {question['question']}")
        print(f"      note  {question.get('note', '')[:96]}")
        print(f"      gold  {sorted(question['sections'])}")
        for section in found:
            body = " ".join(section["head"].split())
            print(f"      ---   {section['id']:<44} {section['heading']!r}")
            print(f"            {body[:150]}")

    print(f"\n{queued} sections to read, over {len(questions)} questions")
    print("Nothing here is a defect until somebody reads it. Widen a gold only")
    print("with the reason written into the file beside the entry.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
