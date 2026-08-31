"""Issue a reader token to one person.

    uv run python -m backend.scripts.mint_token alice

Prints the token once and the environment entry to keep. The token itself is
never written anywhere -- not to a file, not to the graph, not into
`ACCESS_TOKENS` -- so if the person loses it, mint another and drop the old
line. That is the whole revocation story, and it is deliberately that small.

WHY ONE EACH RATHER THAN ONE SHARED PASSWORD: the graph is the prose of two
published books, so access is a list of people the DM has confirmed own them.
A shared secret cannot be revoked from one person, cannot say whose copy
leaked, and spreads without anybody deciding it should.
"""

from __future__ import annotations

import argparse
import sys

from backend.api.auth import fingerprint, mint_token
from backend.core.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("who", help="Whose token this is. For your records only.")
    args = parser.parse_args()

    who = args.who.strip()
    # THE NAME GOES IN A COMMA-SEPARATED, COLON-SEPARATED LIST, so a name
    # holding either character would silently split into two broken entries.
    if not who or "," in who or ":" in who:
        print("a name, holding no comma and no colon", file=sys.stderr)
        return 2

    token = mint_token()
    entry = f"{who}:{fingerprint(token)}"

    existing = (settings.access_tokens or "").strip().rstrip(",")
    combined = f"{existing},{entry}" if existing else entry

    print(f"\ntoken for {who} -- give them this, it is shown once:\n")
    print(f"    {token}\n")
    print("ACCESS_TOKENS, with everyone who already had one:\n")
    print(f"    {combined}\n")
    if not existing:
        print("(nothing was configured before, so this is the first reader.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
