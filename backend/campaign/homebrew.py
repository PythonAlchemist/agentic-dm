"""Turn an approved generation into graph, and take it back out again.

WHAT GETS WRITTEN, and why each part is needed rather than nice to have:

  * an ENTITY, so the thing has a name that resolves. Alias lookup is the only
    name-handle this system has; an episode a DM cannot refer to by name three
    sessions later is invisible to retrieval, to the subgraph, and to the
    context a later generation could carry.
  * its ALIAS, for the same reason -- `resolve_name` reads aliases, not names.
  * a SECTION holding the prose, on the campaign plane. This is what makes the
    DM's own writing RETRIEVABLE: the whole read stack is built on `:Section`,
    and prose stored as a property on an entity would be prose no passage could
    ever return.
  * a MENTION joining the two, because that triangle is how anything comes back
    as a passage at all.
  * one `DERIVED_FROM` per cited canon section, which is the `from_canon` list
    stopping being JSON and becoming structure. It answers a question nothing
    else can: "what in my campaign leans on this passage" -- and, when a
    chapter is re-extracted, which of the DM's material was built on what
    changed.
  * the CHAIN INSERT, when the DM chose a position.

WHAT IS NOT VERIFIED, said plainly because the alternative is a check that only
appears to work. Nothing here confirms that a `from_canon` claim is supported by
the passage it cites, and nothing re-checks the body after a DM edits it. The
citation is a pointer for a human, not a proof. This project has failed four
times at automating that judgement and says so rather than pretending.

DELETE IS THE EXACT INVERSE and exists from the first day. Canon nodes are never
mutated by any of this -- homebrew only ever points AT them -- so removal is a
scoped `DETACH DELETE` plus a chain splice, with nothing left behind to find.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from backend.campaign import store
from backend.campaign.chain import insert_plan, remove_plan, walk
from backend.campaign.model import AUTHORED, CAMPAIGN_PLANE, campaign_prefix, mint_id
from backend.canon.aliases import normalize
from backend.graph.schema import ALIAS_OF, DESCRIBES, IN_SECTION, REFERS_TO

#: What a `cite` looks like in a generation: `[1]`, pointing at a source slot.
_CITE = re.compile(r"\[(\d+)\]")

#: Homebrew entity kinds, mapped from the generator's own `KINDS`. A `scene`
#: becomes an EVENT, which the canon ontology already has (26 of them) -- this
#: invents no vocabulary.
LABELS = {"npc": "NPC", "monster": "MONSTER", "quest": "QUEST", "scene": "EVENT"}

#: A homebrew section cites the canon it was built on.
DERIVED_FROM = "DERIVED_FROM"


class AlreadyStored(Exception):
    """Something in this campaign already has that id. Refused, never merged.

    Two scenes a DM named the same thing are two scenes, and silently folding
    the second into the first would lose one. A campaign is one continuous
    world, so a repeated name is a collision to report, not a merge to perform.
    """

    def __init__(self, entity_id: str) -> None:
        super().__init__(
            f"{entity_id} already exists in this campaign. Rename it, or delete "
            "the existing one first -- nothing was written."
        )
        self.entity_id = entity_id


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@dataclass(frozen=True)
class Stored:
    """What a write put in the graph, counted."""

    entity_id: str
    section_id: str
    citations: int
    chain_changes: int
    anchored_after: str = ""

    def as_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "section_id": self.section_id,
            "citations": self.citations,
            "chain_changes": self.chain_changes,
            "anchored_after": self.anchored_after,
        }


def cited_sections(from_canon, sources) -> tuple[list[str], list[str]]:
    """Resolve `[n]` citations against the sources shown. `(resolved, bad)`.

    VALIDATED AT THE PERSISTENCE BOUNDARY rather than trusted from the client.
    The payload has been round-tripped through a browser and possibly edited by
    hand; a citation pointing at a slot that was never shown is the difference
    between a pointer a human can check and a number that looks like one.
    """
    by_slot = {}
    for index, source in enumerate(sources or (), start=1):
        by_slot[str(index)] = source.get("source") or source.get("section_id") or ""
        marker = str(source.get("citation") or "")
        found = _CITE.search(marker)
        if found:
            by_slot[found.group(1)] = by_slot[str(index)]

    resolved: list[str] = []
    bad: list[str] = []
    for claim in from_canon or ():
        found = _CITE.search(str(claim.get("cite", "")))
        target = by_slot.get(found.group(1)) if found else None
        (resolved if target else bad).append(target or str(claim.get("cite", "")))
    return sorted(set(resolved)), bad


def write(
    tx,
    *,
    slug: str,
    kind: str,
    title: str,
    body: str,
    generated_body: str,
    from_canon,
    invented,
    from_context,
    sources,
    anchor: str | None,
    model: str = "",
    log_path: Path | None = None,
) -> Stored:
    """One transaction: the entity, its prose, its citations, its position."""
    name = title.strip() or "Untitled"
    entity_id = mint_id(slug, slugify(name))
    section_id = f"{campaign_prefix(slug)}{slugify(name)}#0"

    exists = tx.run(
        "MATCH (n) WHERE n.id IN [$e, $s] RETURN count(n) AS c",
        {"e": entity_id, "s": section_id},
    ).single()["c"]
    if exists:
        raise AlreadyStored(entity_id)

    label = LABELS.get(kind, "LORE")
    tx.run(
        f"""
        CREATE (e:Entity:{label} {{
            id:$id, name:$name, plane:$plane, status:$status, campaign:$slug, kind:$kind
        }})
        """,
        {
            "id": entity_id,
            "name": name,
            "plane": CAMPAIGN_PLANE,
            "status": AUTHORED,
            "slug": slug,
            "kind": kind,
        },
    )
    # `normalized` IS NOT OPTIONAL. `BY_ALIAS` matches on it, not on `name`, so
    # an alias written without one is an alias no question can ever resolve --
    # the entity would exist, be chained, be retrievable by position, and be
    # unreachable by its own name. Found by a test asking for the scene by name
    # and getting nothing.
    #
    # MERGED ON `name` ALONE, AND ONLY SET ON CREATE. `Alias.name` carries a
    # GLOBAL uniqueness constraint -- one node per spelling, across every plane
    # and book -- so merging on `{{name, plane}}` finds no campaign-plane node,
    # tries to create a second one, and dies on the constraint. Storing anything
    # named like an existing canon alias raised a raw driver error.
    #
    # `ON CREATE SET` is what keeps canon unmutated: an existing alias node
    # keeps its own `plane` and `normalized`, and merely gains a second
    # `ALIAS_OF`. That is the shape `BY_ALIAS` already documents as legitimate
    # -- "several is a legitimate answer, and the ambiguity travels" -- and the
    # entity-plane filter keeps the campaign entity out of canon reads. Delete
    # stays clean: DETACH DELETE on the entity takes the edge and leaves the
    # canon alias standing.
    tx.run(
        f"""
        MATCH (e:Entity {{id:$id}})
        MERGE (a:Alias {{name:$name}})
        ON CREATE SET a.normalized = $normalized, a.plane = $plane
        MERGE (a)-[:{ALIAS_OF}]->(e)
        """,
        {
            "id": entity_id,
            "name": name,
            "plane": CAMPAIGN_PLANE,
            "normalized": normalize(name),
        },
    )

    # `generated_body` is kept BESIDE `body`, never instead of it: an edited
    # generation and a model's untouched output are different artifacts, and
    # only holding both makes "what did the DM change" answerable at all.
    tx.run(
        """
        MATCH (c:Campaign {slug:$slug})
        CREATE (s:Section {
            id:$id, heading:$heading, text:$body, generated_body:$generated,
            plane:$plane, campaign:$slug, kind:$kind, model:$model,
            from_canon:$from_canon, invented:$invented, from_context:$from_context,
            edited:$edited
        })
        MERGE (c)-[:HAS_SECTION]->(s)
        """,
        {
            "slug": slug,
            "id": section_id,
            "heading": name,
            "body": body,
            "generated": generated_body,
            "plane": CAMPAIGN_PLANE,
            "kind": kind,
            "model": model,
            "from_canon": json.dumps(list(from_canon or ())),
            "invented": json.dumps(list(invented or ())),
            "from_context": json.dumps(list(from_context or ())),
            "edited": body.strip() != generated_body.strip(),
        },
    )
    tx.run(
        f"""
        MATCH (e:Entity {{id:$e}}), (s:Section {{id:$s}})
        CREATE (m:Mention {{plane:$plane, campaign:$slug, surface:$name}})
        CREATE (m)-[:{REFERS_TO}]->(e)
        CREATE (m)-[:{IN_SECTION}]->(s)
        MERGE (s)-[:{DESCRIBES}]->(e)
        """,
        {"e": entity_id, "s": section_id, "plane": CAMPAIGN_PLANE, "slug": slug, "name": name},
    )

    resolved, _bad = cited_sections(from_canon, sources)
    for target in resolved:
        tx.run(
            f"""
            MATCH (s:Section {{id:$s}}), (canon:Section {{id:$t}})
            MERGE (s)-[r:{DERIVED_FROM}]->(canon)
            SET r.plane = $plane, r.campaign = $slug, r.status = $status
            """,
            {
                "s": section_id,
                "t": target,
                "plane": CAMPAIGN_PLANE,
                "slug": slug,
                "status": AUTHORED,
            },
        )

    changes = 0
    if anchor:
        links, start = store.read_chain(tx, slug)
        in_chain = frozenset(walk(links, start, bound=len(links) + 2).order)
        plan = insert_plan(links, start, section_id, anchor)
        result = store.apply_rewire(
            tx, slug, plan, in_chain | {section_id}, log_path=log_path
        )
        changes = result["changed"]

    return Stored(
        entity_id=entity_id,
        section_id=section_id,
        citations=len(resolved),
        chain_changes=changes,
        anchored_after=anchor or "",
    )


def delete(tx, *, slug: str, entity_id: str, log_path: Path | None = None) -> dict:
    """Remove one stored generation and splice the running order shut.

    The exact inverse of `write`, and possible only because canon was never
    mutated: everything this removes was created by that.
    """
    section_id = tx.run(
        f"MATCH (s:Section)-[:{DESCRIBES}]->(:Entity {{id:$id}}) RETURN s.id AS id",
        {"id": entity_id},
    ).single()
    section_id = dict(section_id)["id"] if section_id else ""

    spliced = 0
    if section_id:
        links, start = store.read_chain(tx, slug)
        in_chain = frozenset(walk(links, start, bound=len(links) + 2).order)
        if section_id in in_chain:
            plan = remove_plan(links, start, section_id)
            result = store.apply_rewire(
                tx, slug, plan, in_chain - {section_id}, log_path=log_path
            )
            spliced = result["changed"]

    removed = tx.run(
        """
        MATCH (e:Entity {id:$id, plane:$plane})
        OPTIONAL MATCH (m:Mention)-[:REFERS_TO]->(e)
        OPTIONAL MATCH (a:Alias)-[:ALIAS_OF]->(e)
        DETACH DELETE m, a, e
        RETURN count(e) AS c
        """,
        {"id": entity_id, "plane": CAMPAIGN_PLANE},
    ).single()["c"]

    if section_id:
        tx.run(
            "MATCH (s:Section {id:$id, plane:$plane}) DETACH DELETE s",
            {"id": section_id, "plane": CAMPAIGN_PLANE},
        )
    return {"entity": removed, "section": 1 if section_id else 0, "chain_changes": spliced}
