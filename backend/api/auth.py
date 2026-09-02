"""Who may read the graph, and how the API knows.

THE GRAPH IS TWO PUBLISHED BOOKS. 1,378 canon sections holding 1.6 million
characters of prose from Curse of Strahd and Keys from the Golden Vault. The
reader renders them in full, chat answers quote them, and `/homebrew/section`
returns them whole. `data/` is gitignored for exactly this reason; a public URL
is the same text one step further out.

So the deployment is gated, and the gate is HERE rather than in front of the
web app. A login wall on the frontend leaves the API's own URL reachable, and
whoever finds it gets a searchable copy of both books without ever loading the
page. The frontend carries a credential; this decides whether it is good.

ONE TOKEN PER PERSON, NOT ONE SHARED PASSWORD. The DM confirms each reader
owns the books and issues them a token of their own. That makes access a list
of named people rather than a secret that spreads, lets one be revoked without
disturbing the rest, and means a leaked token says whose it was.

HASHED AT REST. The environment holds SHA-256 of each token, never the token
itself, so the deployment's configuration is not a set of working credentials.
`mint_token` is the only thing that ever sees the plaintext, and it prints it
once for the DM to hand over.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Header, HTTPException

from backend.core.config import settings

#: Paths that answer before the gate. `/health` so a platform can tell whether
#: the process is up without holding a credential, and the docs so a reader
#: reaching the bare URL learns it is a private deployment rather than meeting
#: a bare 401. Neither returns a word of the book.
OPEN_PATHS = frozenset({"/health", "/", "/docs", "/openapi.json", "/redoc"})


def fingerprint(token: str) -> str:
    """The stored form of a token. SHA-256, hex, lower case."""
    return hashlib.sha256(token.encode()).hexdigest()


def mint_token() -> str:
    """A new token for one person. Printed once and never stored in the clear.

    `token_urlsafe(32)` is 256 bits, which is far past guessing and short
    enough to paste into a login box without a mistake.
    """
    return f"dm-{secrets.token_urlsafe(32)}"


class MisconfiguredTokens(RuntimeError):
    """`ACCESS_TOKENS` is set and none of it parses.

    THE ONE FAILURE THE OPEN-WHEN-UNSET RULE DOES NOT COVER. `require_reader`
    is open when NOTHING is configured, which is what makes local development
    and the test suite work, and the argument for it is that a deployment which
    forgets tokens is one nobody can reach -- the frontend would have no token
    to send either.

    That argument does not hold for a MALFORMED value. A quoting mishap or the
    wrong separator leaves `ACCESS_TOKENS` set, every entry dropped, and the
    gate open -- while the frontend's stored token still works, so nobody
    notices. Two published books, served to anyone who finds the URL, announced
    by one startup line nobody reads.
    """


def readers() -> dict[str, str]:
    """`{fingerprint: who}`, read from the environment.

    Configured as `ACCESS_TOKENS="alice:<sha256>,bob:<sha256>"`. The name is
    for the DM's own records -- who was issued what -- and is never shown to a
    caller, since a 401 that names the people who WOULD have got in is telling
    a stranger something.
    """
    found: dict[str, str] = {}
    raw = (settings.access_tokens or "").strip()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        who, _, digest = entry.partition(":")
        found[digest.strip().lower()] = who.strip()
    if raw and not found:
        raise MisconfiguredTokens(
            "ACCESS_TOKENS is set but no entry parses as `name:sha256`. "
            "Refusing to serve, because the alternative is serving two "
            "published books to anyone at all."
        )
    return found


def identify(token: str) -> str:
    """Whose token this is, or `""`.

    COMPARED IN CONSTANT TIME against every entry rather than by dict lookup.
    A hash comparison that returns early leaks how much of a guess was right,
    and the list is a handful of people, so the cost of checking all of them is
    nothing.
    """
    if not token:
        return ""
    offered = fingerprint(token)
    who = ""
    for digest, name in readers().items():
        if hmac.compare_digest(offered, digest):
            who = name
    return who


def reader_of(request) -> str:
    """Whose request this is, as the gate decided it.

    READ FROM THE SCOPE, not re-derived from the header. `ReaderGate` has
    already identified the caller in constant time; a route doing it again
    would be a second implementation of the same rule, free to disagree with
    the one that actually decides whether the request is served.

    Empty when the deployment is open, which is a real answer rather than a
    missing one: nobody was identified because nobody had to be.
    """
    return request.scope.get("reader", "") if request is not None else ""


def require_reader(authorization: str = Header(default="")) -> str:
    """A FastAPI dependency: the caller's name, or 401.

    OPEN WHEN NO TOKENS ARE CONFIGURED, which is what makes local development
    and the test suite work unchanged -- and is safe only because a deployment
    that forgets to set them is a deployment nobody can reach anyway, since the
    frontend would have no token to send either. `main` says so at startup
    rather than leaving it to be discovered.
    """
    if not readers():
        return "anyone (no tokens configured)"
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="this deployment is private; a reader token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    who = identify(token.strip())
    if not who:
        raise HTTPException(status_code=401, detail="that token is not one of ours")
    return who
