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

#: Homebrew kinds mapped to the labels the canon ontology already uses, so a
#: stored thing wears the same type as the book's own. A `scene` becomes an
#: EVENT; nothing here invents vocabulary.
#:
#: COVERS `KINDS` AND `ELEMENT_KINDS` BOTH. The first four are what a DM may
#: ask for outright; `location`, `item` and `lore` arrive only as members of a
#: cluster, and without them every element a quest declared was silently
#: labelled LORE -- a barge and a strongbox filed as folklore.
LABELS = {
    "npc": "NPC",
    "monster": "MONSTER",
    "quest": "QUEST",
    "scene": "EVENT",
    "location": "LOCATION",
    "item": "ITEM",
    "lore": "LORE",
}

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


def write_cluster(
    tx,
    *,
    plan,
    kind: str,
    title: str,
    body: str,
    generated_body: str,
    from_canon,
    invented,
    from_context,
    sources,
    manifest,
    anchor: str | None,
    model: str = "",
    log_path: Path | None = None,
) -> dict:
    """A cluster: one Section of prose, and every element it declares.

    ONE SECTION, MANY ENTITIES. Each element gets a node, an alias and a
    Mention into the SHARED section -- the mention triangle is what makes a
    thing retrievable as a passage, and giving every element its own section
    would multiply the prose a DM has to read without adding a word to it.

    ONE TRANSACTION OR NOTHING, which matters more here than for a single
    artifact: a half-written cluster is entities nobody can find and a section
    describing things that do not exist.

    `plan` is a `cluster.ClusterPlan` and is trusted to have decided WHAT to
    write -- ids minted, collisions resolved, drops counted. Refusing an
    unstorable plan happens at the boundary, before a transaction opens.
    """
    if not plan.storable:
        raise AlreadyStored(
            f"{len(plan.collisions)} unresolved name collision(s); nothing was written"
        )

    root = write(
        tx,
        slug=plan.campaign,
        kind=kind,
        title=title,
        body=body,
        generated_body=generated_body,
        from_canon=from_canon,
        invented=invented,
        from_context=from_context,
        sources=sources,
        anchor=anchor,
        model=model,
        log_path=log_path,
    )
    tx.run(
        """
        MATCH (s:Section {id:$id})
        SET s.manifest = $manifest, s.generated_manifest = $generated
        """,
        {
            "id": root.section_id,
            # BESIDE the model's original, never instead of it -- the
            # `generated_body` rule applied to the manifest, so "what did the
            # DM override" stays answerable after the fact.
            "manifest": json.dumps(
                [
                    {"name": e.name, "kind": e.kind, "entity_id": e.entity_id}
                    for e in plan.elements
                ]
            ),
            "generated": json.dumps(manifest),
        },
    )

    written = []
    for element in plan.elements:
        label = LABELS.get(element.kind, "LORE")
        tx.run(
            f"""
            CREATE (e:Entity:{label} {{
                id:$id, name:$name, plane:$plane, status:$status,
                campaign:$slug, kind:$kind, role:$role,
                from_canon:$from_canon, invented:$invented,
                cluster:$section
            }})
            """,
            {
                "id": element.entity_id,
                "name": element.name,
                "plane": CAMPAIGN_PLANE,
                "status": AUTHORED,
                "slug": plan.campaign,
                "kind": element.kind,
                "role": element.role,
                "from_canon": json.dumps(list(element.from_canon)),
                "invented": json.dumps(list(element.invented)),
                # Which cluster minted it, so delete can find its siblings and
                # a reader can ask what a scene brought into the world.
                "section": root.section_id,
            },
        )
        tx.run(
            f"""
            MATCH (e:Entity {{id:$id}})
            MERGE (a:Alias {{name:$name}})
            ON CREATE SET a.normalized = $normalized, a.plane = $plane
            MERGE (a)-[:{ALIAS_OF}]->(e)
            """,
            {
                "id": element.entity_id,
                "name": element.name,
                "normalized": normalize(element.name),
                "plane": CAMPAIGN_PLANE,
            },
        )
        tx.run(
            f"""
            MATCH (e:Entity {{id:$e}}), (s:Section {{id:$s}})
            CREATE (m:Mention {{plane:$plane, campaign:$slug, surface:$name}})
            CREATE (m)-[:{REFERS_TO}]->(e)
            CREATE (m)-[:{IN_SECTION}]->(s)
            """,
            {
                "e": element.entity_id,
                "s": root.section_id,
                "plane": CAMPAIGN_PLANE,
                "slug": plan.campaign,
                "name": element.name,
            },
        )
        # Each element's OWN citations become structure, unioned with the
        # cluster's: "what in my campaign leans on this passage" has to answer
        # for a scene's cast, not only for the scene.
        for target in cited_sections(element.from_canon, sources)[0]:
            tx.run(
                f"""
                MATCH (s:Section {{id:$s}}), (canon:Section {{id:$t}})
                MERGE (s)-[r:{DERIVED_FROM}]->(canon)
                SET r.plane = $plane, r.campaign = $slug, r.status = $status
                """,
                {
                    "s": root.section_id, "t": target, "plane": CAMPAIGN_PLANE,
                    "slug": plan.campaign, "status": AUTHORED,
                },
            )
        written.append(element.entity_id)

    return {
        **root.as_dict(),
        "elements": written,
        "dropped": dict(plan.dropped),
        "edges_deferred": plan.edges_deferred,
    }


class NotStored(Exception):
    """Asked to flesh out something this campaign does not hold."""

    def __init__(self, entity_id: str) -> None:
        super().__init__(f"{entity_id} is not in this campaign; nothing was written")
        self.entity_id = entity_id


class AlreadyExpanded(Exception):
    """It already has prose of its own. Refused rather than appended to.

    A second write-up is a second opinion about one thing, and silently
    stacking them leaves a DM reading two descriptions with no way to tell
    which is current. Delete the old one and write again, deliberately.
    """

    def __init__(self, entity_id: str, section_id: str) -> None:
        super().__init__(
            f"{entity_id} already has its own section ({section_id}). Delete it "
            "first if you want to write a new one."
        )
        self.entity_id = entity_id
        self.section_id = section_id


def expand(
    tx,
    *,
    slug: str,
    entity_id: str,
    body: str,
    generated_body: str,
    from_canon,
    invented,
    from_context,
    sources,
    anchor: str | None = None,
    model: str = "",
    log_path: Path | None = None,
) -> Stored:
    """Give something that already exists prose of its own.

    A CLUSTER MINTS STUBS. An element gets a node, a name and a role, and the
    only prose beside it is the scene's -- "Corsairs swarm the deck at dawn"
    never says Captain Saltmarrow. This is how that stub becomes something a
    DM can read from at the table.

    IT CREATES NO ENTITY AND NO ALIAS. That is the whole difference from
    `write`, and it is what makes fleshing out an existing thing distinct from
    minting a second one with the same name -- which `AlreadyStored` refuses,
    correctly, and which is what a DM would otherwise hit here.

    ANCHORING IS OPTIONAL AND OFF BY DEFAULT. A character's write-up is not an
    episode: putting it in the running order would tell the table to play it.
    """
    row = tx.run(
        "MATCH (e:Entity {id:$id, plane:$plane, campaign:$slug}) "
        "RETURN e.name AS name, e.kind AS kind",
        {"id": entity_id, "plane": CAMPAIGN_PLANE, "slug": slug},
    ).single()
    if row is None:
        raise NotStored(entity_id)
    name = dict(row)["name"]
    kind = dict(row)["kind"] or "lore"

    section_id = f"{campaign_prefix(slug)}{slugify(name)}#0"
    existing = tx.run(
        "MATCH (s:Section {id:$id}) RETURN s.id AS id", {"id": section_id}
    ).single()
    if existing is not None:
        raise AlreadyExpanded(entity_id, section_id)

    tx.run(
        """
        MATCH (c:Campaign {slug:$slug})
        CREATE (s:Section {
            id:$id, heading:$heading, text:$body, generated_body:$generated,
            plane:$plane, campaign:$slug, kind:$kind, model:$model,
            from_canon:$from_canon, invented:$invented, from_context:$from_context,
            edited:$edited, expands:$entity
        })
        MERGE (c)-[:HAS_SECTION]->(s)
        """,
        {
            "slug": slug, "id": section_id, "heading": name, "body": body,
            "generated": generated_body, "plane": CAMPAIGN_PLANE, "kind": kind,
            "model": model,
            "from_canon": json.dumps(list(from_canon or ())),
            "invented": json.dumps(list(invented or ())),
            "from_context": json.dumps(list(from_context or ())),
            "edited": body.strip() != generated_body.strip(),
            "entity": entity_id,
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
        {"e": entity_id, "s": section_id, "plane": CAMPAIGN_PLANE,
         "slug": slug, "name": name},
    )

    resolved, _bad = cited_sections(from_canon, sources)
    for target in resolved:
        tx.run(
            f"""
            MATCH (s:Section {{id:$s}}), (canon:Section {{id:$t}})
            MERGE (s)-[r:{DERIVED_FROM}]->(canon)
            SET r.plane = $plane, r.campaign = $slug, r.status = $status
            """,
            {"s": section_id, "t": target, "plane": CAMPAIGN_PLANE,
             "slug": slug, "status": AUTHORED},
        )

    changes = 0
    if anchor:
        links, start = store.read_chain(tx, slug)
        in_chain = frozenset(walk(links, start, bound=len(links) + 2).order)
        plan = insert_plan(links, start, section_id, anchor)
        changes = store.apply_rewire(
            tx, slug, plan, in_chain | {section_id}, log_path=log_path
        )["changed"]

    return Stored(
        entity_id=entity_id,
        section_id=section_id,
        citations=len(resolved),
        chain_changes=changes,
        anchored_after=anchor or "",
    )


def delete_cluster(tx, *, slug: str, entity_id: str, cascade: bool = False) -> dict:
    """Remove a cluster root, and refuse by default while its elements remain.

    AN ELEMENT WHOSE ONLY SECTION DIES BECOMES UNRETRIEVABLE AS A PASSAGE. It
    still exists, still resolves by name, and can never come back as prose --
    which is a worse state than either keeping it or removing it, and is not
    something to leave a DM in by accident. So this names them and stops.
    `cascade` is spelled out, and what it removed is counted.
    """
    section = tx.run(
        f"MATCH (s:Section)-[:{DESCRIBES}]->(:Entity {{id:$id}}) RETURN s.id AS id",
        {"id": entity_id},
    ).single()
    section_id = dict(section)["id"] if section else ""

    members = [
        dict(r)["id"]
        for r in tx.run(
            "MATCH (e:Entity {cluster:$s, plane:$p}) RETURN e.id AS id",
            {"s": section_id, "p": CAMPAIGN_PLANE},
        )
    ] if section_id else []

    if members and not cascade:
        raise ClusterHasElements(entity_id, tuple(sorted(members)))

    removed = 0
    for member in members:
        tx.run(
            """
            MATCH (e:Entity {id:$id, plane:$plane})
            OPTIONAL MATCH (m:Mention)-[:REFERS_TO]->(e)
            OPTIONAL MATCH (a:Alias)-[:ALIAS_OF]->(e)
            DETACH DELETE m, e
            WITH a WHERE a IS NOT NULL AND NOT (a)-[:ALIAS_OF]->()
            DELETE a
            """,
            {"id": member, "plane": CAMPAIGN_PLANE},
        )
        removed += 1

    root = delete(tx, slug=slug, entity_id=entity_id)
    return {**root, "elements": removed}


class ClusterHasElements(Exception):
    """Deleting the root would orphan the elements it minted."""

    def __init__(self, entity_id: str, members: tuple[str, ...]) -> None:
        super().__init__(
            f"refusing to delete {entity_id}: {len(members)} element(s) were minted "
            f"with it and would be left with no section to be read from "
            f"({', '.join(members[:3])}). Pass cascade to remove them too."
        )
        self.entity_id = entity_id
        self.members = members
