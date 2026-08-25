# Saved answer-eval runs

A baseline is what `eval_answers --save` writes: pass counts per question and
the sample size, and nothing else. No prose from any book, which is why these
are committed while everything under `data/` is not.

## Why they exist

`eval_answers` runs a model, so its number moves between runs of identical
code. Without a recorded run there is nothing to compare against except
somebody's memory of a number, and a remembered figure cannot carry an
interval. That is not hypothetical: a run measured 64%, was compared against a
remembered 73%, and the honest verdict had to be "this cannot be resolved
either way" -- when the two runs were 4 points apart and the harness could only
resolve 11.

## Using one

    uv run python -m backend.scripts.eval_answers --repeat 12 \
        --save evals/baselines/YYYY-MM-DD-what-changed.json --label "..."

    uv run python -m backend.scripts.eval_answers --compare before.json after.json

`--compare` spends nothing. It reports whether zero sits inside the interval,
and says plainly that a run showing no change does not show the absence of one:
a real effect smaller than the resolvable difference looks exactly the same.

## What these measure

Both books, since `2026-08-25-both-books`. A question declares its `book`;
absent means `cos`. The declaration is explicit rather than derived because an
answer question carries no gold section id to read a prefix off -- unlike the
retrieval set, where the book IS derivable and therefore is.

**Never a campaign.** These construct retrievers with no campaign, so a DM's
own material cannot reach a measurement of what the BOOK supports. That is
pinned by a test asserting the word does not appear in either harness.

## A run is only comparable to one taken over the same questions

Adding questions invalidates a baseline rather than extending it. The 108
sample run below measured ten Barovia questions; the 228 sample run measures
twenty across two books. They are not two points on one line, and `--compare`
will happily subtract them anyway -- it compares numbers, not suites.

## The runs

| File | Samples | Rate | 95% CI | Scope and what had changed |
|---|---|---|---|---|
| `2026-08-25-post-homebrew.json` | 108 | 68% | 58–76% | **Curse of Strahd only.** The campaign chain, homebrew, and the chapter-anchor ranking rule. First recorded baseline; its interval contains the 73% the project had been carrying unrecorded, so nothing suggested a regression. Superseded as a comparison point by the row below. |
| `2026-08-25-both-books.json` | 228 | 73% | 67–79% | **Both books**, ten questions each. Per book: cos 70% (61–78%), kftgv 76% (67–83%). Those intervals overlap heavily, so the six-point gap is NOT a real difference -- 228 samples resolve 7% overall and much less per book. Compare future runs against this one. |

## What the current run says, and does not

Golden Vault scores higher than Curse of Strahd here and LOWER on retrieval
(79% against 85%). The answer gap is inside the noise and should not be
believed; the retrieval gap is deterministic and should. A plausible reading of
why answers hold up is that heist prose states checkable facts -- a DC, a name,
a rule -- so a retrieved section is easy to answer from. That is a story, not a
measurement, and it is written here as one.

Every current failure is the same shape: **the answer is right and uncited.**
b03 quotes the Golden Vault's motto verbatim and fails on citation alone. The
one exception, b06, traces to a retrieval miss the other suite already
records (k11, same section), which is the two instruments agreeing.
