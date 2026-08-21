"""Read the canon graph, and write down every question that was asked of it.

The extraction pipeline has been filling this graph for weeks and almost nothing
reads it. Three questions cover nearly everything a DM asks mid-session -- where
is this, what is here, tell me about this -- so those are the only three tools
here. There is no Cypher passthrough, no cache and no query planner: a caller
that can ask anything teaches us nothing about what it actually asks.

THE LOG IS THE DELIVERABLE. Every call appends one JSON line to
`data/query-log.jsonl`, and an empty answer records WHY it was empty. The graph
holds 3 of the book's 25 chapters and its proposed layer is roughly a third
wrong, so the useful output of running this is not the hits -- it is the list of
misses that says which handful of relationships are worth hand-authoring. A miss
that does not say why is a question we would have to ask again.

WHAT THIS MODULE READS, and every clause of it is load-bearing::

    (:Book)-[:HAS_CHAPTER]->(:Chapter)-[:HAS_SECTION]->(:Section {heading, index, key, text})
    (:Section)-[:DESCRIBES]->(:Entity:LOCATION)
    (:Entity)<-[:REFERS_TO]-(:Mention {offsets})-[:IN_SECTION]->(:Section)
    (:Entity)<-[:ALIAS_OF]-(:Alias)<-[:USES_ALIAS]-(:Mention)

The passage a DM reads is DERIVED from the last two of those -- `section.text`
sliced around `mention.offsets[0]` and trimmed to the sentence, by
`backend/canon/passage.py`. The mention used to store its own copy, which was
35,383 characters of prose the graph already had.

An entity node carries `{id, name, plane, status, votes}` and NOTHING ELSE. Its
type is a LABEL, its rung is a LABEL, and where it appears is a set of
`:Mention` nodes. The previous attempt at this module read `n.entity_type`,
`n.chapter_slug` and `n.section_heading` off the entity, which is why it
returned `section=None` against the real graph while its own fixtures -- which
wrote those properties themselves -- kept its suite green.

Three rules the answers keep:

- **Names resolve through `aliases.resolve_name` and through nothing else.** An
  entity's canonical name is itself an `:Alias`, so that one traversal answers
  under the canonical name, under every authored spelling, and under either
  apostrophe. Matching is exact on `normalized` -- lowercase, trimmed, U+2019
  folded. No edit distance, no prefix rule, no token subset, no substring
  containment. Each of those has already damaged this project once.
- **`accepted` and `proposed` are SEPARATE lists, never merged.** An accepted
  edge is derived from the document's own structure and cannot hallucinate; a
  proposed one is model output measured at 30-50% wrong, and `Ismark OPPOSES
  Ireena` (he is her brother) is sitting in this graph right now. One flat list
  would hand that to a table with the authority of a derived containment.
- **A rung is reported only when a place wears one.** An unclassified place says
  `None`, because unclassified is a real state and defaulting it to `SITE` would
  invent a claim the extraction deliberately declined to make.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from backend.canon.aliases import resolve_name
from backend.canon.gazetteer import load_gazetteer
from backend.canon.passage import derive_passage
from backend.canon.writer import ACCEPTED, CANON_PLANE, LOCATION_SUBTYPE_LABELS
from backend.graph.schema import ARTIFACT_LABEL

logger = logging.getLogger(__name__)

#: Gitignored along with everything else under `data/`. Appended to, never
#: rewritten: the record of what was asked is only worth having if it is whole.
DEFAULT_LOG_PATH = Path("data/query-log.jsonl")

#: The book's own closed set of names, harvested from the wiki index. Used ONLY
#: to tell two kinds of miss apart -- never to match, never to return a result.
DEFAULT_GAZETTEER_PATH = Path("data/gazetteer/curse-of-strahd.json")

#: No `:Alias` answers to this name. Either the name is wrong, or it is an
#: entity nothing has recorded, and the book's index does not know it either.
NAME_NOT_IN_GRAPH = "name_not_in_graph"

#: The entity is here; the relationship is not. THIS is the miss worth
#: hand-authoring -- the graph already has both ends and is missing the edge --
#: so it is diagnosed first and nothing may mask it.
NO_SUCH_RELATIONSHIP = "no_such_relationship"

#: The book's index knows this name and the graph does not hold it. Nothing to
#: author yet; the chapter it lives in has not been extracted.
CHAPTER_NOT_EXTRACTED = "chapter_not_extracted"

#: The two spatial relationships. `LOCATED_IN` points entity -> place and
#: `CONTAINS` points place -> entity, so both are read, in opposite directions.
#: Reading only one would silently halve every spatial answer.
LOCATED_IN = "LOCATED_IN"
CONTAINS = "CONTAINS"

#: `:Entity` is on every node here and says nothing; the rest is the type.
_ENTITY_LABEL = "Entity"


class GazetteerLike(Protocol):
    """The one method this module needs off a gazetteer."""

    def lookup(self, name: str) -> Any: ...


def write_log_record(path: Path, record: dict) -> None:
    """Append one JSON line. Never raises.

    A DM is mid-session when this runs. Losing a log line is bad -- it is the
    whole point of the exercise -- but failing the lookup because the disk is
    full would be worse, so the failure is logged loudly and swallowed.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("canon query log unwritable at %s: %s", path, exc)


def rung_of(labels: list[str]) -> str | None:
    """The place's rung, or `None` when it carries none.

    `None` rather than `""` or a default, and the distinction is the point: the
    writer gives a rung only where the book's key convention or a hand-authored
    seed supplies one, so a place without one is UNCLASSIFIED and has to read
    that way. Guessing `SITE` from the absence would manufacture a claim.

    The writer's rung REPLACES rather than adds, so at most one is ever present;
    `sorted` is only so that a corrupted double never returns at random.
    """
    rungs = sorted(set(labels) & LOCATION_SUBTYPE_LABELS)
    return rungs[0] if rungs else None


def type_labels(labels: list[str]) -> list[str]:
    """What the node is, sorted -- everything but the bare `:Entity`.

    A LIST, because a disputed type genuinely wears two: `Barovia` is
    `:LOCATION:SETTING` and no single string says that. Collapsing to one would
    be the read path choosing on the reader's behalf between two extractions
    that disagreed, which is the same move as a fuzzy match in other clothes.
    """
    return sorted(label for label in labels if label != _ENTITY_LABEL)


def split_by_status(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Accepted rows, then everything else.

    Written as "accepted, and the rest" rather than "accepted, proposed" on
    purpose. `conflicted` -- a proposed edge demoted for contradicting an
    accepted one -- lands in the proposed list carrying its own status, because
    it is a proposed edge that already lost rather than a third trust level; and
    a row that somehow carries no status at all lands there too, because trust
    is earned from evidence and must never be the default.
    """
    accepted = [row for row in rows if row.get("status") == ACCEPTED]
    proposed = [row for row in rows if row.get("status") != ACCEPTED]
    return accepted, proposed


# -- the queries ------------------------------------------------------------
#
# Written out in full rather than composed, because a reader checking that
# nothing fuzzy has crept into the read path should be able to see every MATCH.
# Labels are never interpolated: the only label text these carry is this
# module's own constants, and a rung or a type is read back with `labels(n)`.

SUBJECTS = """
MATCH (n:Entity {plane:$plane}) WHERE n.id IN $ids
RETURN n.id AS id, n.name AS name, labels(n) AS labels, n.status AS node_status
ORDER BY n.id
"""

#: Both directions of the spatial pair, from the entity's end.
PLACEMENTS = f"""
MATCH (n:Entity {{plane:$plane}})-[r:{LOCATED_IN}]->(p:Entity {{plane:$plane}})
WHERE n.id IN $ids
RETURN n.name AS entity, '{LOCATED_IN}' AS relationship,
       p.id AS place_id, p.name AS place, labels(p) AS place_labels, r.status AS status
UNION
MATCH (p:Entity {{plane:$plane}})-[r:{CONTAINS}]->(n:Entity {{plane:$plane}})
WHERE n.id IN $ids
RETURN n.name AS entity, '{CONTAINS}' AS relationship,
       p.id AS place_id, p.name AS place, labels(p) AS place_labels, r.status AS status
"""

#: Where the book actually discusses the thing -- the passage a DM turns to.
#: Read off the mention triangle, NOT off the entity: an entity the whole book
#: shares has no one chapter, and each appearance carries its own section.
PASSAGES = """
MATCH (n:Entity {plane:$plane})<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(s:Section)
WHERE n.id IN $ids
MATCH (c:Chapter)-[:HAS_SECTION]->(s)
RETURN DISTINCT c.slug AS chapter, c.index AS chapter_index, c.title AS chapter_title,
       s.heading AS section, s.index AS section_index, s.key AS section_key
ORDER BY chapter_index, section_index
"""

#: The mirror of `PLACEMENTS`, read from the place's end. Deliberately its own
#: query rather than a re-use with the arrow flipped, so neither can drift.
OCCUPANTS = f"""
MATCH (p:Entity {{plane:$plane}})-[r:{CONTAINS}]->(x:Entity {{plane:$plane}})
WHERE p.id IN $ids
RETURN x.id AS id, x.name AS name, labels(x) AS labels,
       '{CONTAINS}' AS relationship, r.status AS status
UNION
MATCH (x:Entity {{plane:$plane}})-[r:{LOCATED_IN}]->(p:Entity {{plane:$plane}})
WHERE p.id IN $ids
RETURN x.id AS id, x.name AS name, labels(x) AS labels,
       '{LOCATED_IN}' AS relationship, r.status AS status
"""

#: What else the passage about this place says. A keyed section IS the place it
#: names -- that is what `DESCRIBES` records -- so the other entities mentioned
#: in that section are the rest of what a DM reading it would find.
DESCRIBING_SECTIONS = """
MATCH (s:Section)-[:DESCRIBES]->(p:Entity {plane:$plane})
WHERE p.id IN $ids
MATCH (c:Chapter)-[:HAS_SECTION]->(s)
OPTIONAL MATCH (s)<-[:IN_SECTION]-(:Mention)-[:REFERS_TO]->(o:Entity {plane:$plane})
WHERE NOT o.id IN $ids
RETURN c.slug AS chapter, c.index AS chapter_index, s.heading AS section,
       s.index AS section_index, s.key AS section_key,
       [name IN collect(DISTINCT o.name) WHERE name IS NOT NULL] AS also_mentions
ORDER BY chapter_index, section_index
"""

#: Every edge attached to the entity, both ways round. Half of what a DM wants
#: about an NPC is written with the NPC as the TARGET -- `Strahd SEEKS Ireena`
#: is the answer to "what is after Ireena" -- so an out-only read loses it.
EDGES = """
MATCH (n:Entity {plane:$plane})-[r]->(o:Entity {plane:$plane})
WHERE n.id IN $ids
RETURN n.name AS entity, 'out' AS direction, type(r) AS relationship,
       o.id AS other_id, o.name AS other, labels(o) AS other_labels, r.status AS status
UNION
MATCH (o:Entity {plane:$plane})-[r]->(n:Entity {plane:$plane})
WHERE n.id IN $ids
RETURN n.name AS entity, 'in' AS direction, type(r) AS relationship,
       o.id AS other_id, o.name AS other, labels(o) AS other_labels, r.status AS status
"""

#: The evidence, which is the sentence the book actually wrote. `USES_ALIAS`
#: says which spellings it used there -- itself story information, since the
#: party meets `Strahd` well before `Strahd von Zarovich`.
#:
#: THE PASSAGE IS DERIVED, NOT STORED. `s.text` and `m.offsets[0]` come back and
#: `passage.derive_passage` turns them into the sentence; the mention no longer
#: carries a copy of the prose its section already holds. The section text is
#: consumed in `lookup` and never reaches a caller -- shipping it would put the
#: duplication back, on the wire instead of in the graph.
#:
#: ONE ROW PER MENTION, and the `WITH` is what makes that true. A mention may
#: use SEVERAL surface forms -- four sections of chapter 3 and the introduction
#: write both of Strahd's names -- so the obvious join emits one row per
#: `USES_ALIAS` edge and repeats the passage. Measured: 14 mentions, 18 edges,
#: 18 rows, 14 distinct sections. A DM saw `Story Overview` twice and every
#: count taken off the list ran 29% high.
#:
#: Collected rather than DISTINCTed away, because dropping the surface form
#: would cost real information to fix a duplication. `collect` also skips nulls,
#: so a mention with no alias edge yields `[]` and the field's SHAPE never
#: changes with the number of spellings.
MENTIONS = """
MATCH (n:Entity {plane:$plane})<-[:REFERS_TO]-(m:Mention)-[:IN_SECTION]->(s:Section)
WHERE n.id IN $ids
MATCH (c:Chapter)-[:HAS_SECTION]->(s)
OPTIONAL MATCH (m)-[:USES_ALIAS]->(a:Alias)
WITH n, m, c, s, collect(DISTINCT a.name) AS aliases
RETURN n.id AS entity_id, m.id AS mention_id, c.slug AS chapter, c.index AS chapter_index,
       s.heading AS section, s.index AS section_index, s.key AS section_key,
       aliases AS aliases, s.text AS section_text, m.offsets[0] AS offset,
       m.occurrences AS occurrences
ORDER BY chapter_index, section_index, mention_id
"""

#: Which chapters the graph holds. Read off `:Chapter`, because an entity no
#: longer carries a chapter at all -- and because the write path creates the
#: chapter node in the same transaction as its canon, so one cannot exist
#: without the other.
CHAPTERS = """
MATCH (c:Chapter {plane:$plane}) RETURN c.slug AS slug ORDER BY c.index
"""


class CanonLookup:
    """Three read-only questions against the canon plane, all of them logged."""

    def __init__(
        self,
        log_path: Path | str = DEFAULT_LOG_PATH,
        gazetteer: GazetteerLike | None = None,
        gazetteer_path: Path | str = DEFAULT_GAZETTEER_PATH,
    ) -> None:
        self.log_path = Path(log_path)
        self.gazetteer = gazetteer if gazetteer is not None else _load(gazetteer_path)

    # -- the three tools ---------------------------------------------------

    def where_is(self, name: str) -> dict:
        """Where the book puts this entity, and where to read about it.

        `found` tracks the PLACEMENT, not the passages. A thing the book
        discusses in four sections and never places is precisely the miss this
        exercise exists to count -- the node is there and the edge is not -- so
        it has to log as a miss even though `passages` came back full.
        """
        with self._session() as session:
            ids, entities = self._resolve(session, name)
            rows = self._run(session, PLACEMENTS, ids)
            placements = [
                {
                    "entity": row["entity"],
                    "relationship": row["relationship"],
                    "place_id": row["place_id"],
                    "place": row["place"],
                    "place_labels": type_labels(row["place_labels"]),
                    "place_rung": rung_of(row["place_labels"]),
                    "status": row["status"],
                }
                for row in rows
            ]
            passages = self._run(session, PASSAGES, ids)
            return self._finish(
                session,
                tool="where_is",
                args={"name": name},
                subject_key="entities",
                subjects=entities,
                rows=placements,
                extra={"passages": passages},
                extra_counts={"passages": len(passages)},
            )

    def whats_here(self, place: str) -> dict:
        """What the book puts in or under this place, and what else it says.

        Two answers, kept apart because they come from different evidence. The
        occupants are EDGES and carry a trust level; the sections are the
        document's own structure and cannot be wrong in the way an edge can, so
        they are neither accepted nor proposed -- they are simply the passage.
        """
        with self._session() as session:
            ids, places = self._resolve(session, place)
            rows = self._run(session, OCCUPANTS, ids)
            occupants = [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "labels": type_labels(row["labels"]),
                    "rung": rung_of(row["labels"]),
                    "relationship": row["relationship"],
                    "status": row["status"],
                }
                for row in rows
            ]
            sections = self._run(session, DESCRIBING_SECTIONS, ids)
            return self._finish(
                session,
                tool="whats_here",
                args={"place": place},
                subject_key="places",
                subjects=places,
                rows=occupants,
                extra={"sections": sections},
                extra_counts={"sections": len(sections)},
            )

    def lookup(self, name: str) -> dict:
        """The entity itself: labels, rung, mentions with evidence, and edges.

        `found` is the ENTITY here, not the edges. "Tell me about X" is answered
        by the node existing -- its labels, its rung and the sentences the book
        wrote about it are the answer -- so a node with nothing attached is a
        thin hit rather than a miss.
        """
        with self._session() as session:
            ids, entities = self._resolve(session, name)
            rows = self._run(session, EDGES, ids)
            edges = [
                {
                    "entity": row["entity"],
                    "direction": row["direction"],
                    "relationship": row["relationship"],
                    "other_id": row["other_id"],
                    "other": row["other"],
                    "other_labels": type_labels(row["other_labels"]),
                    "other_rung": rung_of(row["other_labels"]),
                    "status": row["status"],
                }
                for row in rows
            ]
            mentions = [self._mention(row) for row in self._run(session, MENTIONS, ids)]
            return self._finish(
                session,
                tool="lookup",
                args={"name": name},
                subject_key="entities",
                subjects=entities,
                rows=edges,
                found=bool(entities),
                extra={"mentions": mentions},
                extra_counts={"mentions": len(mentions)},
            )

    # -- the machinery, which is deliberately small ------------------------

    @staticmethod
    def _mention(row: dict) -> dict:
        """One mention row, with its passage derived and its section dropped.

        `evidence` keeps its name because it is the same answer to the same
        question -- what the book says here -- and only its storage changed.

        `pop` rather than a copy without the key: the section text must not
        survive into the result by any path, and popping fails loudly if the
        query ever stops returning it rather than silently shipping `None`.

        `offset or 0` is deliberately NOT written. A first-word mention has
        offset 0, and a truthiness check would send every one of them to the
        top of the section -- which is where they already are, so the bug would
        be invisible exactly where it is wrong.
        """
        row = dict(row)
        text = row.pop("section_text") or ""
        offset = row.pop("offset")
        row["evidence"] = derive_passage(text, offset if offset is not None else 0)
        # `collect` gives no order guarantee, so two runs of the same question
        # would otherwise print the spellings differently.
        row["aliases"] = sorted(row["aliases"])
        return row

    def _session(self):
        """A session per call. No pooling of our own, no cache of answers."""
        from backend.core.database import neo4j_session

        return neo4j_session()

    def _resolve(self, session, name: str) -> tuple[list[str], list[dict]]:
        """Ids and descriptors for every entity that answers to `name`.

        ONE call to `resolve_name` and no fallback behind it. There is no
        second tier here -- no case pass, no slug pass, no near-match -- because
        `normalized` already folds case and the apostrophe, and anything beyond
        that is the inference an `:Alias` node exists to make unnecessary.

        A LIST, never a best guess. `Barovia` names a region and a village;
        `Tatyana` is an NPC and a piece of lore. Collapsing them would be the
        graph choosing between two things the book genuinely distinguishes.
        """
        ids = resolve_name(session, name, plane=CANON_PLANE)
        if not ids:
            return [], []
        return ids, [
            {
                "id": row["id"],
                "name": row["name"],
                "labels": type_labels(row["labels"]),
                "rung": rung_of(row["labels"]),
                "artifact": ARTIFACT_LABEL in row["labels"],
                "node_status": row["node_status"],
            }
            for row in self._rows(session, SUBJECTS, {"ids": ids})
        ]

    def _rows(self, session, query: str, params: dict | None = None) -> list[dict]:
        merged = {"plane": CANON_PLANE, **(params or {})}
        return [dict(record) for record in session.run(query, merged)]

    def _run(self, session, query: str, ids: list[str]) -> list[dict]:
        """Run a query for the resolved subjects, or nothing if there are none."""
        return self._rows(session, query, {"ids": ids}) if ids else []

    def _finish(
        self,
        session,
        *,
        tool: str,
        args: dict,
        subject_key: str,
        subjects: list[dict],
        rows: list[dict],
        found: bool | None = None,
        extra: dict | None = None,
        extra_counts: dict | None = None,
    ) -> dict:
        """Assemble the answer, diagnose an empty one, and log the call."""
        accepted, proposed = split_by_status(rows)
        hit = bool(rows) if found is None else found
        result: dict = {
            "tool": tool,
            "query": next(iter(args.values())),
            "found": hit,
            subject_key: subjects,
            "accepted": accepted,
            "proposed": proposed,
            "count": len(rows),
            "miss_reason": None,
            "miss_detail": "",
            "chapters_in_graph": [],
            **(extra or {}),
        }
        if not hit:
            chapters = [row["slug"] for row in self._rows(session, CHAPTERS)]
            reason, detail = self._diagnose(result["query"], subjects, chapters)
            result["miss_reason"] = reason
            result["miss_detail"] = detail
            result["chapters_in_graph"] = chapters
        self._log(tool, args, result, extra_counts or {})
        return result

    def _diagnose(
        self, name: str, subjects: list[dict], chapters: list[str]
    ) -> tuple[str, str]:
        """Why the answer was empty, in terms a reader can act on months later.

        The order matters and is not negotiable. A name the graph HOLDS but has
        no edge for is the finding worth having -- both ends are already there
        and only the relationship is missing -- so it is checked first and can
        never be masked by anything the book's index says.
        """
        if subjects:
            kinds = ", ".join(sorted({":".join(s["labels"]) or "Entity" for s in subjects}))
            return (
                NO_SUCH_RELATIONSHIP,
                f"{len(subjects)} canon node(s) answer to {name!r} ({kinds}), "
                "none with an edge of the kind asked for",
            )
        entry = self.gazetteer.lookup(name) if self.gazetteer else None
        if entry is not None:
            return (
                CHAPTER_NOT_EXTRACTED,
                f"the book's index knows {entry.name!r} ({entry.entity_type}); "
                f"the graph holds {len(chapters)} chapter(s)",
            )
        return (
            NAME_NOT_IN_GRAPH,
            f"no :Alias in the canon plane answers to {name!r}, "
            "and the book's index does not know it either",
        )

    def _log(self, tool: str, args: dict, result: dict, extra_counts: dict) -> None:
        """One line per call. Misses carry their reason and the graph's coverage.

        The extra counts travel on a HIT as well as a miss, because "placed
        nowhere, but discussed in four sections" and "placed nowhere and never
        mentioned" are different findings and the log has to tell them apart.
        """
        record: dict = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool": tool,
            "args": args,
            "found": result["found"],
            "resolved": len(result.get("entities", result.get("places", []))),
            "results": result["count"],
            "accepted": len(result["accepted"]),
            "proposed": len(result["proposed"]),
            **extra_counts,
        }
        if not result["found"]:
            record["miss_reason"] = result["miss_reason"]
            record["miss_detail"] = result["miss_detail"]
            record["chapters_in_graph"] = result["chapters_in_graph"]
        write_log_record(self.log_path, record)


def _load(path: Path | str) -> GazetteerLike | None:
    """The book's index if it is on disk, and None if it is not.

    Absent is normal -- `data/` is gitignored -- and it costs only the ability
    to tell `chapter_not_extracted` from `name_not_in_graph`. Nothing else here
    depends on it, so a missing file must not stop a DM looking anything up.
    """
    try:
        return load_gazetteer(path)
    except (OSError, ValueError, KeyError) as exc:
        logger.info("canon gazetteer unavailable at %s: %s", path, exc)
        return None
