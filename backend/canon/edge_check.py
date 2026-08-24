"""Does the sentence the extractor cited actually say what the edge claims?

THE NUMBER THIS PROJECT QUOTES ABOUT ITSELF -- "roughly a third of proposed
edges are wrong" -- comes from one hand read of thirty edges in chapter 3. It
has been repeated in a dozen docstrings and in every answer the agent gives
about trust, and nothing has measured it since. Meanwhile the two books in the
graph were extracted to different standards, so it cannot be one number.

WHAT MAKES THIS CHECKABLE, where inferring a relationship type from
co-occurrence was not: the extractor stored the sentence it read. A verdict is
therefore about a claim and its stated evidence, and a person can settle any
disagreement in the time it takes to read one sentence. `cooccurrence` refuses
to automate a judgment with no evidence attached; this one has it attached.

WHAT IT MEASURED, and the second result cost real money to learn.

    Curse of Strahd, 128 edges by vote count   supported   95% CI
        3 votes                                     48%    33-63%
        5 votes                                     57%    42-71%
        overall                                     54%    45-62%

    Golden Vault, same chapters both ways      supported   95% CI
        one sample, every edge kept                 53%    45-61%
        five samples, edge kept at three            51%    43-59%

CONSENSUS DOES NOT BUY PRECISION. Measured twice by different methods -- by
vote stratum inside one book, and by a controlled A/B extracting the same
chapters both ways -- and neither can distinguish five passes from one. The
five-sample arm is nominally WORSE. It costs five times the extraction spend.

The reason is the one this project already knew about a neighbouring problem:
consensus filters UNSTABLE output, and these errors are stable. A model that
misreads a sentence misreads it the same way five times, so five passes agree
on the mistake and the vote count records agreement rather than truth. Five
passes do move `reversed` (6 -> 2 in the A/B), which is a small real effect on
one narrow class and not worth 5x on its own.

THE MODEL MAY NOT USE WHAT IT KNOWS ABOUT D&D. It is asked whether THIS
sentence supports THIS claim, and a true statement the sentence does not make
is still `unsupported`. Otherwise the check would grade the extractor against
the model's memory of Barovia, and agreement between two models that have both
read the internet is not evidence about this graph.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

#: What a verdict may be. A fixed set, because a free-text answer cannot be
#: counted and a rate is the whole point of the exercise.
SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
REVERSED = "reversed"
UNCLEAR = "unclear"
VERDICTS = frozenset({SUPPORTED, UNSUPPORTED, REVERSED, UNCLEAR})


@dataclass(frozen=True)
class Verdict:
    """One edge, judged against its own evidence."""

    key: str
    verdict: str
    why: str = ""

    @property
    def wrong(self) -> bool:
        """`reversed` counts as wrong. It is a real relationship pointing the
        wrong way, which reads as a fact and is a different fact."""
        return self.verdict in {UNSUPPORTED, REVERSED}


PROMPT = """\
Each item below is a claim an extractor made about a D&D adventure, and the
sentence it read when it made the claim.

For each, judge ONLY whether that sentence supports that claim:

- supported   the sentence states the claim, or plainly implies it
- reversed    the sentence states this relationship the OTHER WAY round
- unsupported the sentence does not state the claim
- unclear     the sentence is too vague or truncated to tell

Judge the SENTENCE, not the adventure. If you happen to know the claim is true
but this sentence does not say it, that is `unsupported`. If the sentence
mentions both things without relating them the way the claim does, that is
`unsupported` too -- appearing together is not a relationship.

Items:
{items}

Return JSON: {{"verdicts": [{{"key": "...", "verdict": "...", "why": "..."}}]}}
`why` is at most twelve words. Every key above must appear exactly once.
"""


def render(edges: Iterable[dict]) -> str:
    """The items block. `key` is what ties a verdict back to its edge."""
    lines = []
    for edge in edges:
        lines.append(
            f"key: {edge['key']}\n"
            f"  claim: {edge['source']} -{edge['rel_type']}-> {edge['target']}\n"
            f"  sentence: {edge['evidence']}"
        )
    return "\n\n".join(lines)


def parse(payload: str, offered: Iterable[str]) -> tuple[list[Verdict], list[str]]:
    """Read one response. Returns `(verdicts, refusals)`.

    A verdict for a key that was not asked about is refused, and so is one
    carrying a word that is not a verdict. Both mean the model stopped
    following the form, and a rate built from answers to questions nobody
    asked is not a measurement.
    """
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        return [], [f"unparseable response: {exc}"]

    allowed = set(offered)
    seen: set[str] = set()
    verdicts: list[Verdict] = []
    refused: list[str] = []
    for entry in raw.get("verdicts") or []:
        key, verdict = entry.get("key", ""), entry.get("verdict", "")
        if key not in allowed:
            refused.append(f"verdict for a key nobody asked about: {key!r}")
            continue
        if verdict not in VERDICTS:
            refused.append(f"{key}: {verdict!r} is not a verdict")
            continue
        if key in seen:
            refused.append(f"{key}: judged twice")
            continue
        seen.add(key)
        verdicts.append(Verdict(key=key, verdict=verdict, why=entry.get("why", "")))

    # An edge asked about and not answered is a MISSING measurement, not a pass.
    for key in sorted(allowed - seen):
        refused.append(f"{key}: no verdict returned")
    return verdicts, refused


def precision(verdicts: Iterable[Verdict]) -> dict:
    """Counts and a supported-rate. `unclear` is excluded from the rate.

    Excluded rather than counted either way: an unreadable sentence says
    nothing about whether the extractor was right, and folding it into either
    column would move the number for a reason that is not about edges.
    """
    counted = list(verdicts)
    tally = {v: sum(1 for x in counted if x.verdict == v) for v in sorted(VERDICTS)}
    decided = len(counted) - tally[UNCLEAR]
    tally["decided"] = decided
    tally["supported_rate"] = (tally[SUPPORTED] / decided) if decided else None
    return tally
