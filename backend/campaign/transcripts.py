"""What was actually said at the table, put where the graph can read it.

A TRANSCRIPT IS EVIDENCE, NOT ASSERTION. Four hours of a recording is the least
reliable prose this system will ever hold -- people misremember, joke, argue
about rules, and say a name for a character who is not there. So a transcript
becomes exactly two things: `:Section` nodes holding what was said, and
`:Mention` triangles saying which known names were said in them. It mints no
entity and writes no relationship. "Somebody said Strahd at 9:14" is checkable
against the text; "Strahd betrayed Ireena" is a claim, and a claim read out of
a recording by a model, stored beside the book's, is the exact failure this
project exists to prevent.

IT REUSES `homebrew.rescan` RATHER THAN GROWING A SECOND SCANNER. A transcript
section is a campaign-plane section like any other, so the matcher that already
carries the single-word case rule, the common-noun filter and the anthology
scoping does this job unchanged. The old processor ran a separate NER pipeline
with `create_missing_entities=True` pointed at the same graph -- a second
matcher with different rules AND permission to invent.

IT REPLACES RATHER THAN APPENDS. Re-uploading a session's transcript is what a
DM does when the first upload was the wrong file or half the recording; a store
that appended would leave both in the graph with no way to tell which was
which.

THE IDS ARE THE CAMPAIGN'S. `hb:<slug>:session-<n>-t<i>`, so `delete_campaign`
sweeps them and `scannable_in` reads the middle segment as this table's scope.
The old processor minted `session_<uuid4>` ids carrying no campaign at all,
which made its debris invisible even to the orphan check.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How much of a recording goes in one section.
#:
#: BIG ENOUGH TO BE A SCENE, SMALL ENOUGH TO QUOTE. A mention's passage is
#: derived from its section's text plus an offset, so a section holding the
#: whole evening would make every quote unreadable and every co-occurrence
#: meaningless -- two names four hours apart are not in the same breath. A
#: section holding one utterance would make co-occurrence impossible instead.
CHUNK_CHARS = 1800


@dataclass(frozen=True)
class Said:
    """One turn at the table. `speaker` is a person, never a character."""

    speaker: str
    text: str
    role: str = ""


def section_id(slug: str, number: int, part: int) -> str:
    return f"hb:{slug}:session-{number}-t{part}"


def chunk(said: list[Said], budget: int = CHUNK_CHARS) -> list[list[Said]]:
    """Pack turns into sections, never splitting one.

    A TURN IS ATOMIC because the offsets are. Cutting mid-sentence would put
    half a name at the end of one section and half at the start of the next,
    and the scan would find neither -- a silent zero, which is the failure mode
    this codebase keeps finding and keeps refusing to accept.
    """
    packed: list[list[Said]] = []
    run: list[Said] = []
    size = 0
    for turn in said:
        cost = len(turn.speaker) + len(turn.text) + 2
        if run and size + cost > budget:
            packed.append(run)
            run, size = [], 0
        run.append(turn)
        size += cost
    if run:
        packed.append(run)
    return packed


def render(said: list[Said]) -> str:
    """`Speaker: what they said`, one per line.

    THE SPEAKER'S NAME IS PART OF THE TEXT, deliberately. It is what makes a
    quote readable back to a DM -- "who said that?" is the first question -- and
    the scan treats it like any other prose, which is correct: a player saying
    a character's name is that name being said at the table.
    """
    return "\n".join(f"{turn.speaker}: {turn.text}".strip() for turn in said)


CLEAR = """
MATCH (:Session {id:$session, campaign:$slug})-[:TRANSCRIBED_AS]->(s:Section)
OPTIONAL MATCH (m:Mention)-[:IN_SECTION]->(s)
DETACH DELETE m, s
RETURN count(s) AS n
"""

WRITE = """
MATCH (c:Campaign {slug:$slug}), (sess:Session {id:$session, campaign:$slug})
CREATE (s:Section {
  id:$id, heading:$heading, text:$text, plane:'campaign', campaign:$slug,
  kind:'transcript', index:$index, spoken_by:$speakers
})
MERGE (c)-[:HAS_SECTION]->(s)
MERGE (sess)-[:TRANSCRIBED_AS]->(s)
RETURN s.id AS id
"""

#: Which of a session's PLANNED scenes the recording appears to have touched.
#:
#: A SUGGESTION, AND IT WRITES NOTHING. `COVERED` is a DM's claim about their
#: own evening, and deriving it from name overlap would be a model deciding
#: what happened at a table it was not at. The overlap is real evidence and
#: worth showing; it is not a verdict, so it goes back as a list to press
#: rather than as an edge.
TOUCHED = """
MATCH (sess:Session {id:$session, campaign:$slug})-[:PLANNED]->(scene:Section)
MATCH (:Mention)-[:REFERS_TO]->(e:Entity)<-[:REFERS_TO]-(:Mention)-[:IN_SECTION]->(scene)
WITH scene, e
MATCH (t:Mention)-[:REFERS_TO]->(e)
MATCH (t)-[:IN_SECTION]->(said:Section {kind:'transcript', campaign:$slug})
MATCH (sess)-[:TRANSCRIBED_AS]->(said)
WITH scene, collect(DISTINCT e.name) AS names
RETURN scene.id AS section_id, scene.heading AS heading, names,
       size(names) AS shared
ORDER BY shared DESC, scene.id
LIMIT 25
"""


def record(tx, *, slug: str, session: str, number: int,
           said: list[Said], budget: int = CHUNK_CHARS) -> dict:
    """Store what was said, and link it to every name the graph already knows.

    Returns counts, not prose: how many sections were written and how many
    mentions the scan supported. A DM reading "412 turns became 9 sections and
    47 mentions" can tell at a glance whether the upload was the right file.
    """
    from backend.campaign import homebrew

    cleared = tx.run(CLEAR, {"slug": slug, "session": session}).single()["n"]

    written: list[str] = []
    for index, part in enumerate(chunk(said, budget)):
        row = tx.run(WRITE, {
            "slug": slug, "session": session,
            "id": section_id(slug, number, index),
            "heading": f"Session {number}, part {index + 1}",
            "text": render(part), "index": index,
            "speakers": sorted({turn.speaker for turn in part if turn.speaker}),
        }).single()
        if row is None:
            raise ValueError(
                f"no session {session!r} on table {slug!r} to transcribe")
        written.append(row["id"])

    scanned = 0
    for one in written:
        scanned += homebrew.rescan(tx, slug=slug, section_id=one)["scanned"]

    return {"replaced": cleared, "sections": len(written),
            "mentions": scanned, "turns": len(said)}


def touched(tx, *, slug: str, session: str) -> list[dict]:
    """Planned scenes whose cast the recording names. A prompt, not a record."""
    return [dict(r) for r in tx.run(TOUCHED, {"slug": slug, "session": session})]
