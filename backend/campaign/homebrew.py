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
from backend.campaign.model import (
    AUTHORED,
    CAMPAIGN_PLANE,
    DRAWS_ON,
    campaign_prefix,
    mint_id,
)
from backend.canon.aliases import normalize
from backend.graph.schema import (
    ALIAS_OF,
    DESCRIBES,
    IN_SECTION,
    LAYER_MAP,
    REFERS_TO,
    RelationshipType,
)

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


def split_by_origin(from_canon, sources) -> tuple[list[dict], list[dict]]:
    """Which of these claims the BOOK supports, and which the DM's own material
    does. `(from_canon, from_yours)`.

    THE MODEL IS ASKED TO SEPARATE THESE AND CANNOT BE TRUSTED TO. It is shown
    one numbered list of passages, and once a campaign has its own prose that
    list holds both planes -- so `from_canon` came back citing [10] and [11],
    "A corsair closes on the barge" and "Corsairs swarm the deck at dawn",
    against two scenes the DM had written the week before. The word `corsair`
    does not appear anywhere in either published book. The card said "From the
    book" over it, in green, which is the one thing this project exists to get
    right.

    So it is DERIVED, not asked for. Every citation already resolves to a
    passage whose plane is known, and a claim citing a campaign passage is not
    a claim about the book whatever the model called it. That makes this a
    check rather than a hope, which is the only kind of guarantee worth
    printing next to a colour.

    AN UNRESOLVABLE CITE STAYS PUT. `cited_sections` is what reports those, and
    moving a claim on the strength of a citation that points nowhere would be
    guessing in the opposite direction.
    """
    origins = {}
    for index, source in enumerate(sources or (), start=1):
        origin = str(source.get("type") or source.get("origin") or "")
        origins[str(index)] = origin
        found = _CITE.search(str(source.get("citation") or ""))
        if found:
            origins[found.group(1)] = origin

    book: list[dict] = []
    yours: list[dict] = []
    for claim in from_canon or ():
        found = _CITE.search(str(claim.get("cite", "")))
        origin = origins.get(found.group(1)) if found else None
        (yours if origin and origin != "canon" else book).append(dict(claim))
    return book, yours


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
    from_yours=(),
    anchor: str | None,
    model: str = "",
    log_path: Path | None = None,
) -> Stored:
    """One transaction: the entity, its prose, its citations, its position."""
    # DERIVED HERE AND NOT TAKEN FROM THE PAYLOAD, for the reason
    # `cited_sections` gives just below: this has been round-tripped through a
    # browser. A claim citing a campaign passage is not a claim about the book,
    # whatever reached this function calling it one.
    book, yours = split_by_origin([*from_canon, *from_yours], sources)
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
            from_canon:$from_canon, from_yours:$from_yours,
            invented:$invented, from_context:$from_context,
            edited:$edited, expands:$entity
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
            "from_canon": json.dumps(book),
            "from_yours": json.dumps(yours),
            "invented": json.dumps(list(invented or ())),
            "from_context": json.dumps(list(from_context or ())),
            "edited": body.strip() != generated_body.strip(),
            # SET BY BOTH WRITERS, so `expands` means "the section that is this
            # entity's own prose" rather than "the section `expand` made".
            # Reading it as the second told a DM that seven scenes they had
            # written up were "still just a name", offered to flesh out prose
            # that already existed, and left those rows unopenable.
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

    # LAST, so the prose exists to be read and every element this write minted
    # is already a candidate. A scene naming its own cast then links to them
    # because the words say so, not only because the manifest listed them.
    rescan(tx, slug=slug, section_id=section_id)
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
    from_yours=(),
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
        from_yours=from_yours,
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
        # An element's citations run through the same check as a section's: the
        # model is shown one numbered list, and a stub can misfile a campaign
        # passage exactly as a body can.
        element_book, element_yours = split_by_origin(element.from_canon, sources)
        tx.run(
            f"""
            CREATE (e:Entity:{label} {{
                id:$id, name:$name, plane:$plane, status:$status,
                campaign:$slug, kind:$kind, role:$role,
                from_canon:$from_canon, from_yours:$from_yours,
                invented:$invented, cluster:$section
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
                "from_canon": json.dumps(element_book),
                "from_yours": json.dumps(element_yours),
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

    # THE LINKS. A mention from this scene's section to the BOOK's entity,
    # which is how "my scene involves Marta Marthannis" becomes something the
    # graph can answer. Nothing about the canon node changes: a mention points
    # AT it, the same shape `DERIVED_FROM` already uses for canon sections.
    #
    # It stays out of canon reads by construction rather than by a filter --
    # `MENTIONS` requires the section to hang off a `:Chapter`, and a campaign
    # section hangs off a `:Campaign`. A test pins that.
    linked = 0
    for name, canon_id in plan.links:
        tx.run(
            f"""
            MATCH (e:Entity {{id:$e, plane:'canon'}}), (s:Section {{id:$s}})
            CREATE (m:Mention {{plane:$plane, campaign:$slug, surface:$name}})
            CREATE (m)-[:{REFERS_TO}]->(e)
            CREATE (m)-[:{IN_SECTION}]->(s)
            """,
            {"e": canon_id, "s": root.section_id, "plane": CAMPAIGN_PLANE,
             "slug": plan.campaign, "name": name},
        )
        linked += 1

    # THE RELATIONSHIPS, between things this cluster minted and the generation
    # itself. `plan_cluster` has already thrown out every edge whose endpoint
    # types the book's own domain/range table forbids, so what arrives here is
    # type-valid and the only thing left to do is name it.
    #
    # `layer` COMES FROM THE SCHEMA, never from the model. It is what partitions
    # the graph into surfaces, and letting a generation choose its own would
    # let one edge sit on a layer nothing else of its type sits on.
    by_name = {e.name.casefold(): e.entity_id for e in plan.elements}
    by_name[title.strip().casefold()] = root.entity_id
    edges_written = 0
    for source, target, rel_type in plan.edges:
        relationship = RelationshipType(rel_type)  # raises on anything unknown
        layer = LAYER_MAP.get(relationship)
        tx.run(
            f"""
            MATCH (a:Entity {{id:$a}}), (b:Entity {{id:$b}})
            MERGE (a)-[r:{relationship.value}]->(b)
            SET r.plane = $plane, r.campaign = $slug, r.status = $status,
                r.layer = $layer
            """,
            {
                "a": by_name[source.casefold()],
                "b": by_name[target.casefold()],
                "plane": CAMPAIGN_PLANE,
                "slug": plan.campaign,
                "status": AUTHORED,
                "layer": layer.value if layer else "",
            },
        )
        edges_written += 1

    # AGAIN, and not redundantly: `write` scanned before this function minted a
    # single element, so its pass could not match a name that did not exist
    # yet. This is the one that sees the cast.
    scan = rescan(tx, slug=plan.campaign, section_id=root.section_id)
    return {
        **root.as_dict(),
        "elements": written,
        "scanned": scan["scanned"],
        "linked_to_canon": linked,
        "dropped": dict(plan.dropped),
        "edges": edges_written,
        "edges_dropped": dict(plan.edges_dropped),
    }


#: A scanned mention says so, because reconciliation must not touch the ones
#: `write_cluster` states outright. "This scene contains Captain Saltmarrow" is
#: a fact about the manifest, true whether or not the prose ever spells his
#: name; "this scene says `Revel\u2019s End`" is a fact about the text and stops
#: being true when the DM deletes the words. One is authored, the other derived,
#: and a rescan may only overwrite what it wrote.
SCANNED = "scanned"


def rescan(tx, *, slug: str, section_id: str) -> dict:
    """Link a homebrew section to every entity its prose actually names.

    THE PROSE WAS INVISIBLE. A cluster wrote one mention per declared element
    and one per canon link, and nothing read the words. So a scene whose text
    said "Captain Saltmarrow" three times was connected to him only because the
    manifest happened to list him, and The Sea Battle -- which names him and
    was written before he existed as an element -- was connected to him not at
    all. Asking about him did not surface the scene he is in.

    IT REUSES THE CANON SCANNER RATHER THAN GROWING A SECOND ONE.
    `spine.scan_mentions` carries rules this needs and would otherwise have to
    re-derive: the single-word case rule that keeps the LORE entity `Light` off
    every lit torch, the common-noun filter, and the chapter-scoping rule. That
    last one does real work here for free -- a chapter-scoped canon id is
    scannable only inside its own chapter and a homebrew section is in none, so
    thirteen heists' worth of `Guard` and `Kitchen` cannot match. Only names
    the book itself treats as book-wide can.

    CANON ENTITIES ARE IN SCOPE ON PURPOSE. A DM writing "the barge reaches
    Revel's End" has said their scene involves the book's prison, which is
    exactly what the cluster's `link` choice records by hand. Nothing about the
    canon node changes: a campaign-plane mention points AT it, and `MENTIONS`
    requires a `:Chapter` that a campaign section does not have, so canon reads
    are unaffected by construction.

    RECONCILES RATHER THAN APPENDS, which is what makes it safe to re-run after
    an edit. A name the DM deleted should stop being a mention, and a scan that
    only ever added would leave the graph asserting the old text forever.
    """
    from backend.canon.spine import EntityNames, WriteSection, scan_mentions

    # READ HERE rather than taken as a parameter: every caller would have had
    # to fetch the same thing, and a caller that passed the wrong books would
    # scan a scene against a book its table is not playing.
    # The `DRAWS_ON` edges, which is where a campaign's books actually live --
    # there is no `books` property, and reading one returned an empty list that
    # scanned nothing and then reconciled away everything a correct scan had
    # found. Exactly the behaviour reconciliation is for, pointed the wrong way.
    books = [
        r["slug"]
        for r in tx.run(
            f"MATCH (:Campaign {{slug:$slug}})-[:{DRAWS_ON}]->(b:Book) "
            "RETURN b.slug AS slug",
            {"slug": slug},
        )
        if r["slug"]
    ]

    row = tx.run(
        """
        MATCH (s:Section {id:$id, plane:$plane, campaign:$slug})
        RETURN s.text AS text, s.heading AS heading
        """,
        {"id": section_id, "plane": CAMPAIGN_PLANE, "slug": slug},
    ).single()
    if row is None:
        raise NotEditable(section_id)

    candidates = [
        EntityNames(
            id=r["id"], name=r["name"], aliases=tuple(a for a in (r["aliases"] or []) if a)
        )
        for r in tx.run(
            """
            MATCH (e:Entity)
            WHERE (e.plane = $plane AND e.campaign = $slug)
               OR (e.plane = 'canon' AND any(b IN $books WHERE e.id STARTS WITH b + ':'))
            OPTIONAL MATCH (a:Alias)-[:ALIAS_OF]->(e)
            RETURN e.id AS id, e.name AS name, collect(a.name) AS aliases
            """,
            {"plane": CAMPAIGN_PLANE, "slug": slug, "books": list(books)},
        )
    ]

    section = WriteSection(
        id=section_id,
        # THE CAMPAIGN IS THE SCOPE, and passing it here is what makes one rule
        # do the right thing on both planes. `spine.scannable_in` asks whether
        # an id's middle segment matches the scope it is being read in, which
        # for `cos:castle-ravenloft:k61a-closet` means a chapter and for
        # `hb:p13-home:captain-saltmarrow` means a campaign. Passing "" made
        # every campaign entity unscannable -- the whole point of this pass --
        # while passing the campaign lets a table see its own cast and still
        # keeps thirteen heists' worth of `Guard` and `Kitchen` out, since
        # their middle segment is a chapter name and never this.
        chapter_slug=slug,
        heading=dict(row)["heading"] or "",
        index=0,
        depth=0,
        parent_index=-1,
        text=dict(row)["text"] or "",
    )
    found = scan_mentions([section], candidates, chapter_slug=slug)

    kept = set()
    for mention in found:
        tx.run(
            f"""
            MATCH (e:Entity {{id:$entity_id}}), (s:Section {{id:$section_id}})
            MERGE (m:Mention {{id:$id}})
            SET m += $props, m.plane = $plane, m.campaign = $slug, m.{SCANNED} = true
            MERGE (m)-[:{REFERS_TO}]->(e)
            MERGE (m)-[:{IN_SECTION}]->(s)
            """,
            {
                "id": mention.id,
                "entity_id": mention.entity_id,
                "section_id": section_id,
                "props": mention.properties,
                "plane": CAMPAIGN_PLANE,
                "slug": slug,
            },
        )
        kept.add(mention.id)

    dropped = tx.run(
        f"""
        MATCH (m:Mention)-[:{IN_SECTION}]->(:Section {{id:$section_id}})
        WHERE m.{SCANNED} = true AND NOT m.id IN $kept
        DETACH DELETE m
        RETURN count(m) AS n
        """,
        {"section_id": section_id, "kept": list(kept)},
    ).single()["n"]
    return {"scanned": len(kept), "dropped": dropped}


class NotEditable(Exception):
    """Asked to change prose this campaign does not own.

    Covers a section that is not here and a section that is the BOOK's in one
    message, deliberately: from the caller's side both are "you may not write
    that", and distinguishing them would tell an unrelated campaign whether an
    id exists.
    """

    def __init__(self, section_id: str) -> None:
        super().__init__(
            f"{section_id} is not this campaign's to edit; nothing was written"
        )
        self.section_id = section_id


def edit(tx, *, slug: str, section_id: str, body: str) -> dict:
    """Change the prose of something already stored.

    THE ONLY WAY TO FIX A LINE WAS TO DELETE AND REGENERATE, which threw away
    the citations, the placement in the running order, and every element a
    cluster had minted -- to change a name. Reading your own material makes
    wanting to correct it the immediate next thing, so this is that.

    `generated_body` IS NOT TOUCHED. It is what the model wrote and this is
    what the DM made of it; holding both is the only thing that keeps "what did
    a person change" answerable, and an edit that overwrote it would erase the
    answer at the moment it starts being interesting.

    `edited` IS RE-DERIVED, not set. It is `body != generated_body`, the same
    expression `write` uses, so a DM who edits back to the model's exact words
    stops being told their provenance is stale -- because it no longer is.

    THE CITATIONS ARE LEFT ALONE AND GO STALE. They were made about the text
    the model wrote. Nothing re-checks a body after a person edits it, the card
    has always said so, and the reader says so too. Silently dropping them
    would be worse: a DM who fixed a typo would lose the pointers.

    CANON IS NOT EDITABLE THROUGH HERE. The plane check is in the MATCH rather
    than in a branch after it, so there is no path that reads a canon section
    and then decides.
    """
    row = tx.run(
        """
        MATCH (s:Section {id:$id, plane:$plane, campaign:$slug})
        RETURN s.generated_body AS generated, s.text AS text
        """,
        {"id": section_id, "plane": CAMPAIGN_PLANE, "slug": slug},
    ).single()
    if row is None:
        raise NotEditable(section_id)

    generated = dict(row)["generated"] or ""
    tx.run(
        "MATCH (s:Section {id:$id}) SET s.text = $body, s.edited = $edited",
        {"id": section_id, "body": body, "edited": body.strip() != generated.strip()},
    )
    return {
        "section_id": section_id,
        "edited": body.strip() != generated.strip(),
        "changed": body.strip() != (dict(row)["text"] or "").strip(),
        # The prose IS the scanner's input and it just changed, so a name the
        # DM deleted stops being a mention in the same transaction that
        # deleted it. Leaving it to a later pass means the graph asserts the
        # old text for however long that takes.
        **rescan(tx, slug=slug, section_id=section_id),
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
    from_yours=(),
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
    book, yours = split_by_origin([*from_canon, *from_yours], sources)  # as in `write`
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
            from_canon:$from_canon, from_yours:$from_yours,
            invented:$invented, from_context:$from_context,
            edited:$edited, expands:$entity
        })
        MERGE (c)-[:HAS_SECTION]->(s)
        """,
        {
            "slug": slug, "id": section_id, "heading": name, "body": body,
            "generated": generated_body, "plane": CAMPAIGN_PLANE, "kind": kind,
            "model": model,
            "from_canon": json.dumps(book),
            "from_yours": json.dumps(yours),
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

    # LAST, so the prose exists to be read and every element this write minted
    # is already a candidate. A scene naming its own cast then links to them
    # because the words say so, not only because the manifest listed them.
    rescan(tx, slug=slug, section_id=section_id)
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
