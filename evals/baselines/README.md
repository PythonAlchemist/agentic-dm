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

## What these currently measure

**Curse of Strahd only.** All ten answer questions are Barovia, the same
one-book flaw the retrieval suite carried until Golden Vault questions were
added to it. A baseline taken here describes one book, and adding questions
from another will invalidate it for comparison -- take a fresh one at that
point rather than comparing across a changed suite.

## The runs

| File | Samples | Rate | 95% CI | What had changed |
|---|---|---|---|---|
| `2026-08-25-post-homebrew.json` | 108 | 68% | 58–76% | The campaign chain, homebrew storage and retrieval, and the chapter-anchor ranking rule. First recorded baseline; the interval contains the 73% this project had been carrying as an unrecorded figure, so nothing here suggests a regression. |
