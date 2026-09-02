"""Making a table, and the few things that are true of the whole of it.

A CAMPAIGN COULD ONLY BE MADE BY A SCRIPT. `store.create` has existed all
along and the only caller was `backend/scripts/create_campaign.py`, so the
product's home page told a DM "the lab can create one" -- which was not true
of the lab either. The first thing a person does with this product had no
button.

SETTINGS ARE PROPERTIES; THE PREMISE IS PROSE. A name and a list of books are
facts about the container and live on the `:Campaign` node. What the campaign
IS -- the pitch, the house rules, what the party did before session one -- is
writing, and writing in this system is a `:Section` in the campaign plane. So
the premise is stored as one, which means it is scanned for names like every
other authored section: a premise saying "the party owes money to Bildrath"
connects the table to Bildrath, for free, by going through the machinery that
already exists rather than around it.

ONE PREMISE PER TABLE, AT A FIXED ID. `hb:<slug>:the-premise` -- there is
exactly one answer to "what is this campaign", and a list would invite three
half-written ones with no way to tell which is current.

BOOKS CAN BE ADDED, AND REMOVING ONE IS NOT A DELETE. `DRAWS_ON` is what scopes
every search and every mention scan, so dropping a book stops new mentions
being found in it -- it does not remove what the table already wrote, and it
must not, because those are the DM's own words about the book they read.
"""

from __future__ import annotations

from backend.campaign.model import CAMPAIGN_PLANE, DRAWS_ON


def premise_id(slug: str) -> str:
    return f"hb:{slug}:the-premise"


BOOKS = """
MATCH (b:Book)
OPTIONAL MATCH (b)-[:HAS_CHAPTER]->(ch:Chapter)
RETURN b.slug AS slug, coalesce(b.title, b.slug) AS title,
       count(ch) AS chapters
ORDER BY b.slug
"""

SETTINGS = """
MATCH (c:Campaign {slug:$slug})
OPTIONAL MATCH (c)-[:DRAWS_ON]->(b:Book)
OPTIONAL MATCH (c)-[:HAS_SECTION]->(p:Section {id:$premise})
RETURN c.slug AS slug, c.name AS name, coalesce(c.owner, '') AS owner,
       [x IN collect(b.slug) WHERE x IS NOT NULL] AS books,
       coalesce(p.text, '') AS premise
"""

RENAME = """
MATCH (c:Campaign {slug:$slug})
SET c.name = $name
RETURN c.slug AS slug, c.name AS name
"""

DRAW_ON = f"""
MATCH (c:Campaign {{slug:$slug}}), (b:Book {{slug:$book}})
MERGE (c)-[:{DRAWS_ON}]->(b)
RETURN b.slug AS slug
"""

STOP_DRAWING = f"""
MATCH (:Campaign {{slug:$slug}})-[r:{DRAWS_ON}]->(:Book {{slug:$book}})
DELETE r RETURN count(r) AS n
"""

WRITE_PREMISE = """
MATCH (c:Campaign {slug:$slug})
MERGE (s:Section {id:$id})
ON CREATE SET s.heading = $heading, s.plane = $plane, s.campaign = $slug,
              s.kind = 'premise'
SET s.text = $text, s.edited = true
MERGE (c)-[:HAS_SECTION]->(s)
RETURN s.id AS id
"""


def books(tx) -> list[dict]:
    """Every book the graph holds, for the picker on the setup screen."""
    return [dict(r) for r in tx.run(BOOKS)]


def settings(tx, *, slug: str) -> dict:
    """What is true of the whole table."""
    row = tx.run(SETTINGS, {"slug": slug, "premise": premise_id(slug)}).single()
    if row is None:
        raise ValueError(f"no table {slug!r}")
    return dict(row)


def rename(tx, *, slug: str, name: str) -> dict:
    """Change what the table is called. Never what it is KEYED by.

    THE SLUG IS THE ID AND IS NOT EDITABLE. Every campaign node in the graph
    carries the slug -- entities, sections, mentions, edges, holdings -- so
    renaming it is a migration, not a setting, and offering it as one would
    quietly orphan a whole table.
    """
    if not name.strip():
        raise ValueError("a table needs a name")
    row = tx.run(RENAME, {"slug": slug, "name": name.strip()}).single()
    if row is None:
        raise ValueError(f"no table {slug!r}")
    return dict(row)


def draw_on(tx, *, slug: str, book: str) -> str:
    """Add a book this table plays from."""
    row = tx.run(DRAW_ON, {"slug": slug, "book": book}).single()
    if row is None:
        raise ValueError(f"no table {slug!r} or no book {book!r}")
    return str(row["slug"])


def stop_drawing(tx, *, slug: str, book: str) -> int:
    """Stop playing from a book.

    WHAT THE TABLE ALREADY WROTE SURVIVES. This removes an edge, not prose:
    new scans will no longer look in that book, and every section the DM wrote
    about it stays exactly where it is.
    """
    return tx.run(STOP_DRAWING, {"slug": slug, "book": book}).single()["n"]


def write_premise(tx, *, slug: str, text: str) -> dict:
    """Say what this campaign is, as prose the graph can read.

    IT IS SCANNED LIKE ANY OTHER SECTION, which is the whole reason it is a
    section. A premise naming Bildrath connects the table to Bildrath through
    the machinery that already exists, rather than through a second path that
    would have to be kept in step with it.
    """
    row = tx.run(WRITE_PREMISE, {
        "slug": slug, "id": premise_id(slug), "text": text,
        "heading": "What this campaign is", "plane": CAMPAIGN_PLANE,
    }).single()
    if row is None:
        raise ValueError(f"no table {slug!r}")
    return dict(row)
