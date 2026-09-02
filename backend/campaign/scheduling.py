"""When the table can actually sit down.

THE HARDEST PART OF D&D IS NOT THE RULES. It is six adults and a calendar, and
the reason it belongs in this product rather than in a group chat is that the
answer is a fact about the campaign -- the same thing that holds the sessions,
the party and the running order.

A DATE IS A NODE, AND AN ANSWER IS AN EDGE. The DM proposes dates; each player
answers for themselves. Modelling availability as a property on a player would
hold one date; modelling it as a node per (player, date) would mint a node for
a shrug. An edge carrying `answer` is exactly the claim being made.

SILENCE IS NOT A NO. An unanswered date is UNKNOWN, and the count says so
separately, because a screen that renders "no reply" as "cannot make it"
schedules around people who simply have not looked at their phone -- and then
the one evening everybody was free is the one the DM ruled out.

A PLAYER ANSWERS FOR THEMSELVES. The answerer comes from the seat, never from
the request body, for the same reason the map's audience does: a field a client
fills in is a field a client can fill in wrongly, and "somebody marked me
unavailable" is a bug that looks exactly like a scheduling disagreement.

`:Sitting` IS APPARATUS. A proposed evening asserts nothing about the world, so
it carries no `plane` -- see `schema.APPARATUS_LABELS` -- and it carries
`campaign`, so `delete_campaign` sweeps it.
"""

from __future__ import annotations

YES = "yes"
NO = "no"
MAYBE = "maybe"
ANSWERS = frozenset({YES, NO, MAYBE})


def sitting_id(slug: str, on: str) -> str:
    """`hb:<campaign>:sitting-<date>`, so proposing the same evening twice is
    one date rather than two identical rows nobody can tell apart."""
    return f"hb:{slug}:sitting-{on}"


PROPOSE = """
MATCH (c:Campaign {slug:$slug})
MERGE (s:Sitting {id:$id})
ON CREATE SET s.campaign = $slug, s.on = $on, s.note = $note
MERGE (c)-[:MAY_SIT]->(s)
RETURN s.id AS id, s.on AS on
"""

WITHDRAW = """
MATCH (s:Sitting {id:$id, campaign:$slug})
DETACH DELETE s RETURN count(s) AS n
"""

ANSWER = """
MATCH (s:Sitting {id:$id, campaign:$slug})
MERGE (p:Player {reader:$reader, campaign:$slug})
MERGE (p)-[a:CAN_MAKE]->(s)
SET a.answer = $answer, a.campaign = $slug
RETURN a.answer AS answer
"""

#: Every proposed evening with who said what.
#:
#: THE THREE COUNTS ARE SEPARATE, AND SO IS SILENCE. `yes`, `no` and `maybe`
#: are claims somebody made; `seated` is how many people could have made one.
#: A single "4 available" number would collapse "two people said no" and "two
#: people have not answered" into the same display, and those lead to opposite
#: decisions.
SITTINGS = """
MATCH (:Campaign {slug:$slug})-[:MAY_SIT]->(s:Sitting)
OPTIONAL MATCH (p:Player {campaign:$slug})-[a:CAN_MAKE]->(s)
WITH s, collect({reader: p.reader, answer: a.answer}) AS answers
RETURN s.id AS id, s.on AS on, coalesce(s.note, '') AS note,
       [x IN answers WHERE x.answer = 'yes' | x.reader] AS yes,
       [x IN answers WHERE x.answer = 'no' | x.reader] AS no,
       [x IN answers WHERE x.answer = 'maybe' | x.reader] AS maybe
ORDER BY s.on
"""

SEATED_COUNT = """
MATCH (p:Player {campaign:$slug})-[:PLAYS_IN]->(:Campaign {slug:$slug})
RETURN count(p) AS n
"""

#: Pin a session to the evening it was actually played on.
HELD_ON = """
MATCH (sess:Session {id:$session, campaign:$slug}),
      (s:Sitting {id:$sitting, campaign:$slug})
SET sess.held_on = s.on
MERGE (sess)-[:HELD_AT]->(s)
RETURN sess.id AS id, sess.held_on AS held_on
"""


def propose(tx, *, slug: str, on: str, note: str = "") -> dict:
    """Put an evening on the table.

    `on` IS A DATE STRING AND THIS MODULE DOES NOT PARSE IT. A table that says
    "the 14th" or "2026-09-14" or "Thursday after next" all mean something to
    the six people in it, and a validator here would reject the shorthand the
    group actually uses while adding no correctness anybody wanted.
    """
    if not on.strip():
        raise ValueError("a sitting needs an evening")
    row = tx.run(PROPOSE, {
        "slug": slug, "id": sitting_id(slug, on.strip()),
        "on": on.strip(), "note": note,
    }).single()
    if row is None:
        raise ValueError(f"no table {slug!r} to sit at")
    return dict(row)


def withdraw(tx, *, slug: str, sitting: str) -> int:
    """Take an evening off the table, and its answers with it.

    DELETED, NOT CLOSED -- unlike a holding. A withdrawn date is not a fact
    about the past, it is a question that was asked and then unasked, and
    keeping it would clutter the one screen whose value is being scannable.
    """
    return tx.run(WITHDRAW, {"slug": slug, "id": sitting}).single()["n"]


def answer(tx, *, slug: str, sitting: str, reader: str, says: str) -> str:
    """Say whether you can make it. For yourself, and only for yourself."""
    if says not in ANSWERS:
        raise ValueError(f"{says!r} is not an answer: {sorted(ANSWERS)}")
    if not reader:
        raise ValueError("an answer needs somebody to have given it")
    row = tx.run(ANSWER, {"slug": slug, "id": sitting, "reader": reader,
                          "answer": says}).single()
    if row is None:
        raise ValueError(f"no sitting {sitting!r}")
    return str(row["answer"])


def sittings(tx, *, slug: str) -> list[dict]:
    """Every proposed evening, with who said what and how many never said."""
    seated = tx.run(SEATED_COUNT, {"slug": slug}).single()["n"]
    found = []
    for row in tx.run(SITTINGS, {"slug": slug}):
        one = dict(row)
        one["seated"] = seated
        # SILENCE COUNTED SEPARATELY, never folded into `no`.
        one["unanswered"] = max(
            0, seated - len(one["yes"]) - len(one["no"]) - len(one["maybe"]))
        found.append(one)
    return found


def hold_on(tx, *, slug: str, session: str, sitting: str) -> dict:
    """Say that this session was the one played on that evening."""
    row = tx.run(HELD_ON, {"slug": slug, "session": session,
                           "sitting": sitting}).single()
    if row is None:
        raise ValueError(f"no session {session!r} or sitting {sitting!r}")
    return dict(row)
