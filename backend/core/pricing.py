"""What a call cost, estimated from a table a human has to keep honest.

The table is `pricing.yaml` beside this file. Nothing here fetches a rate, and
nothing infers one: a model absent from the table has no price, and that is
reported rather than guessed at, because a guessed rate looks exactly like a
checked one once it reaches a dollar figure on a screen.

`last_verified` travels with every estimate for the same reason. A cost is a
claim about the outside world made by a file that may not have been touched in
months, and the only defence a reader has is knowing how old it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TABLE = Path(__file__).with_name("pricing.yaml")

#: Rates are quoted per million tokens because that is how vendors quote them.
#: Converting at the point of use rather than storing a per-token float keeps
#: the number in the file identical to the number on the vendor's page, which is
#: what makes the file checkable by a human at a glance.
PER = 1_000_000


@dataclass(frozen=True)
class Usage:
    """Tokens one call consumed."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        """Two calls' usage, summed.

        A turn is no longer one call: the agent may reach into the graph and
        come back. Reporting only the final call would tell somebody a turn
        cost a fraction of what it did, and the cost shown beside an answer is
        the number a person paying for this actually acts on.
        """
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    @classmethod
    def from_response(cls, response: Any) -> "Usage":
        """Read an OpenAI response's usage block, tolerating its absence.

        A streamed or mocked response may carry no usage at all. Zeroes are the
        honest reading -- they show as zero on the dashboard rather than as a
        plausible-looking number nobody can source.
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return cls()
        return cls(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )


@dataclass(frozen=True)
class Cost:
    """An estimate, and everything needed to distrust it."""

    usd: float | None
    model: str
    last_verified: date | None
    #: True when the model is not in the table at all. Distinct from a rate that
    #: exists but nobody has confirmed: one is "we do not know what this costs",
    #: the other is "we have a number of unknown age".
    unpriced: bool = False

    @property
    def verified(self) -> bool:
        return self.last_verified is not None

    def as_dict(self) -> dict:
        return {
            "usd": self.usd,
            "model": self.model,
            "last_verified": self.last_verified.isoformat() if self.last_verified else None,
            "verified": self.verified,
            "unpriced": self.unpriced,
        }


def load_table(path: Path | str = DEFAULT_TABLE) -> dict[str, dict]:
    """The rate table, as written. No defaults are filled in."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    return data.get("models", {}) or {}


def models(path: Path | str = DEFAULT_TABLE) -> list[dict]:
    """Every model the dashboard may offer, with its rates and their age.

    Order is the file's order, which is the author's chosen order -- cheapest
    first here -- rather than alphabetical. A dashboard listing `gpt-4o` above
    `gpt-4o-mini` invites the expensive click.
    """
    return [
        {
            "id": model_id,
            "label": entry.get("label", model_id),
            "note": entry.get("note", ""),
            "input_per_1m": entry.get("input_per_1m"),
            "output_per_1m": entry.get("output_per_1m"),
            "last_verified": _as_iso(entry.get("last_verified")),
        }
        for model_id, entry in load_table(path).items()
    ]


def estimate(model: str, usage: Usage, path: Path | str = DEFAULT_TABLE) -> Cost:
    """What that call probably cost, or an honest refusal to say.

    Returns `usd=None` for a model the table does not list. The alternative --
    falling back to some other model's rate, or to zero -- produces a number
    that is wrong in a direction nobody can see.
    """
    entry = load_table(path).get(model)
    if entry is None:
        return Cost(usd=None, model=model, last_verified=None, unpriced=True)

    input_rate = entry.get("input_per_1m")
    output_rate = entry.get("output_per_1m")
    if input_rate is None or output_rate is None:
        return Cost(usd=None, model=model, last_verified=_as_date(entry.get("last_verified")),
                    unpriced=True)

    usd = (usage.input_tokens * float(input_rate) + usage.output_tokens * float(output_rate)) / PER
    return Cost(usd=usd, model=model, last_verified=_as_date(entry.get("last_verified")))


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return None


def _as_iso(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None
