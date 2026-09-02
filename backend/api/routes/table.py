"""The table's own API: who sits at it, what it played, and what it can see.

WHY A SECOND ROUTER RATHER THAN MORE OF `homebrew.py`. That module is one
thing -- approving a generation into the graph -- and it is already 1200 lines
of it. Seats, sessions, maps and pictures are a different thing: they are the
table's own record, not the drafting flow, and every one of them is read by
people the drafting flow never serves.

THE AUDIENCE IS DERIVED FROM THE SEAT, NEVER TAKEN FROM THE REQUEST. A client
does not get to say "show me the DM view"; it says who it is, `roles.role_of`
says what chair that is, and the route picks the query. A boolean in the body
would mean the guarantee held only as long as every client stayed honest, and
the whole point of a player view is that it survives a dishonest one.

`preview` IS THE ONE FLAG, AND IT ONLY EVER NARROWS. A DM asking what the table
sees is a real need -- it is how you check before you share a screen -- so the
flag can drop a DM to the player view and can never raise anybody to the DM's.
"""

from __future__ import annotations

import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.api import auth
from backend.api.routes.homebrew import guard
from backend.campaign import (
    assets,
    inventory,
    maps,
    roles,
    scheduling,
    sessions,
)
from backend.core.config import settings
from backend.core.database import neo4j_session, read_only_session

#: A `ReadOnlySession` exposes `run` and nothing else -- deliberately, because
#: `execute_write` on a read-mode session bypasses the access mode Neo4j would
#: otherwise enforce. Every campaign read function takes something with `.run`,
#: so the wrapper IS the transaction here, and a write cannot be reached from
#: any of the GET routes below even by accident.

router = APIRouter()


def now_iso() -> str:
    """THE SERVER STAMPS THE TIME, not the client. `held_on` is a date a DM
    types and may be any evening they like; `created_at` is a record of when
    the row was written, and a client's clock is not evidence of that."""
    return datetime.now(UTC).isoformat()

#: Uploading arbitrary bytes and serving them back is how a site becomes a
#: file host for somebody else's malware. An allowlist of image types, checked
#: against the declared type AND used to pick the extension on disk, keeps the
#: store to what a portrait or a map can actually be.
IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

#: 20MB. A book map scan is a few megabytes; anything past this is a mistake or
#: an attack, and either way the answer is the same.
MAX_UPLOAD = 20 * 1024 * 1024


def _reader(http: Request) -> str:
    return auth.reader_of(http)


def _for_player(http: Request, campaign: str, preview: bool = False) -> bool:
    """Which view this request gets.

    THE DEFAULT IS THE PLAYER'S. A reader with no seat, an unknown token, a
    role the graph has forgotten -- every one of those falls to the narrow
    view. Defaulting the other way would mean a bug in seating is a spoiler.
    """
    if preview:
        return True
    reader = _reader(http)
    if not reader:
        # THE OPEN DEPLOYMENT. `ACCESS_TOKENS` unset means nobody is
        # identified; there is one person at the machine and they are running
        # the game. Locking them out of their own map would be the rule's only
        # effect -- the same ruling `roles.role_of` documents.
        return False
    with read_only_session() as session:
        role = roles.role_of(session, slug=campaign, reader=reader)
    return role != roles.DM


# ---------------------------------------------------------------- seats


class SeatRequest(BaseModel):
    campaign: str
    reader: str
    role: str


@router.get("/seats")
def list_seats(campaign: str) -> dict:
    with read_only_session() as session:
        return {"seats": roles.seated(session, slug=campaign)}


@router.get("/me")
def whoami(http: Request, campaign: str) -> dict:
    """The chair this request is sitting in, which the UI needs before it can
    decide what to even offer."""
    reader = _reader(http)
    with read_only_session() as session:
        role = roles.role_of(session, slug=campaign, reader=reader)
    return {"reader": reader, "role": role, "identified": bool(reader)}


@router.post("/seat")
def take_seat(http: Request, request: SeatRequest) -> dict:
    guard(http, request.campaign)
    try:
        with neo4j_session() as session:
            role = session.execute_write(lambda tx: roles.seat(
                tx, slug=request.campaign, reader=request.reader,
                role=request.role))
    except ValueError as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad
    if not role:
        raise HTTPException(
            status_code=404, detail=f"no table {request.campaign!r}")
    return {"reader": request.reader, "role": role}


@router.delete("/seat")
def leave_seat(http: Request, campaign: str, reader: str) -> dict:
    guard(http, campaign)
    with neo4j_session() as session:
        return {"removed": session.execute_write(
            lambda tx: roles.unseat(tx, slug=campaign, reader=reader))}


# ------------------------------------------------------------- sessions


class OpenSessionRequest(BaseModel):
    campaign: str
    title: str = ""
    held_on: str = ""
    number: int | None = None


class SceneRequest(BaseModel):
    campaign: str
    session: str
    section: str
    rank: int = 0


@router.get("/sessions")
def list_sessions(campaign: str) -> dict:
    with read_only_session() as session:
        return {"sessions": sessions.sessions(session, slug=campaign)}


@router.post("/session")
def open_session(http: Request, request: OpenSessionRequest) -> dict:
    guard(http, request.campaign)
    try:
        with neo4j_session() as session:
            return session.execute_write(lambda tx: sessions.open_session(
                tx, slug=request.campaign, title=request.title,
                held_on=request.held_on or now_iso(), number=request.number))
    except ValueError as bad:
        raise HTTPException(status_code=404, detail=str(bad)) from bad


@router.post("/session/plan")
def plan_scene(http: Request, request: SceneRequest) -> dict:
    guard(http, request.campaign)
    with neo4j_session() as session:
        return {"planned": session.execute_write(lambda tx: sessions.plan(
            tx, slug=request.campaign, session=request.session,
            section=request.section, rank=request.rank))}


@router.delete("/session/plan")
def unplan_scene(http: Request, campaign: str, session_id: str,
                 section: str) -> dict:
    guard(http, campaign)
    with neo4j_session() as session:
        return {"removed": session.execute_write(lambda tx: sessions.unplan(
            tx, slug=campaign, session=session_id, section=section))}


@router.post("/session/cover")
def cover_scene(http: Request, request: SceneRequest) -> dict:
    """What the table actually reached, which is a different claim from what
    was meant -- see `sessions.py` on why these are two edges."""
    guard(http, request.campaign)
    with neo4j_session() as session:
        return {"covered": session.execute_write(lambda tx: sessions.cover(
            tx, slug=request.campaign, session=request.session,
            section=request.section))}


@router.get("/session/diff")
def session_diff(campaign: str, session_id: str) -> dict:
    """Planned against covered, computed on read and stored nowhere."""
    with read_only_session() as session:
        return sessions.diff(session, slug=campaign, session=session_id)


class TranscriptRequest(BaseModel):
    campaign: str
    session: str
    content: str
    #: `json`, `discord`, `timestamped`, `plain` -- or unset, and the parser
    #: works it out. Kept because a caller who KNOWS should not have to hope.
    format_hint: str = ""


@router.post("/session/transcript")
def store_transcript(http: Request, request: TranscriptRequest) -> dict:
    """Store what was actually said, and link it to names the graph knows.

    IT WRITES SECTIONS AND MENTIONS, AND NOTHING ELSE. No entity is minted and
    no relationship is written -- see `campaign/transcripts.py` for why a
    recording is the one document in this system that may not assert.
    """
    guard(http, request.campaign)
    from backend.campaign import transcripts
    from backend.transcript.parser import TranscriptParser

    parsed = TranscriptParser().parse(
        request.content, request.format_hint or None, None)
    said = [
        transcripts.Said(speaker=segment.speaker or "",
                         text=segment.text or "",
                         role=getattr(segment.speaker_role, "value", "") or "")
        for segment in parsed.segments
        if (segment.text or "").strip()
    ]
    if not said:
        raise HTTPException(
            status_code=400,
            detail="nothing was said in that file -- the parser found no turns")

    with read_only_session() as session:
        row = session.run(
            "MATCH (s:Session {id:$id, campaign:$slug}) RETURN s.number AS n",
            {"id": request.session, "slug": request.campaign}).single()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no session {request.session!r}")

    try:
        with neo4j_session() as session:
            return session.execute_write(lambda tx: transcripts.record(
                tx, slug=request.campaign, session=request.session,
                number=row["n"], said=said))
    except ValueError as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad


@router.get("/session/touched")
def transcript_touched(campaign: str, session_id: str) -> dict:
    """Planned scenes the recording appears to have reached.

    EVIDENCE, NOT A VERDICT. `COVERED` is a DM's claim about their own evening;
    deriving it from name overlap would be a model deciding what happened at a
    table it was not at. So this comes back as a list to press.
    """
    from backend.campaign import transcripts

    with read_only_session() as session:
        return {"touched": transcripts.touched(
            session, slug=campaign, session=session_id)}


# --------------------------------------------------------------- lookup

#: Entities a table may reach: the books it draws on, plus what it wrote.
#:
#: SCOPED BY BOOK, BECAUSE A NAME BELONGS TO THE ADVENTURE THAT SAYS IT. The
#: mention scan once read every book's entities against one book's prose and
#: produced 332 cross-book mentions; a search that offered a DM running one
#: adventure the cast of another would be the same mistake with a person in the
#: loop instead of a script. `DRAWS_ON` is already the record of which books a
#: table set out with.
#:
#: PREFIX MATCHES RANK ABOVE CONTAINED ONES. Somebody typing "bar" wants
#: Barovia before they want "Blood of the Vine Tavern", and a search that makes
#: a DM read the whole list mid-session is a search they stop using.
SEARCH = """
MATCH (c:Campaign {slug:$slug})
OPTIONAL MATCH (c)-[:DRAWS_ON]->(b:Book)
WITH collect(b.slug + ':') AS prefixes
MATCH (e:Entity)
WHERE toLower(e.name) CONTAINS toLower($q)
  AND (e.campaign = $slug
       OR any(p IN prefixes WHERE e.id STARTS WITH p))
  AND ($label = '' OR $label IN labels(e))
RETURN e.id AS entity_id, e.name AS name, e.plane AS plane,
       [l IN labels(e) WHERE l <> 'Entity'] AS labels,
       coalesce(e.named_by_book, true) AS named_by_book
ORDER BY CASE WHEN toLower(e.name) STARTS WITH toLower($q) THEN 0 ELSE 1 END,
         size(e.name), e.name
LIMIT $limit
"""


@router.get("/search")
def search_entities(campaign: str, q: str, label: str = "",
                    limit: int = 20) -> dict:
    """Find something to pin, to portray, or to open.

    A ROW CAP THE CALLER CANNOT LIFT PAST 50. This is the shape every read the
    model can reach already has, and it is worth keeping on a read a person
    reaches too: a search box that can ask for the whole graph is a search box
    that will, on the evening the graph is largest.
    """
    if not q.strip():
        return {"found": []}
    with read_only_session() as session:
        rows = session.run(SEARCH, {
            "slug": campaign, "q": q.strip(), "label": label,
            "limit": max(1, min(int(limit), 50)),
        })
        return {"found": [dict(r) for r in rows]}


# ----------------------------------------------------------------- maps


class MapRequest(BaseModel):
    campaign: str
    name: str
    place: str
    asset: str


class PinRequest(BaseModel):
    campaign: str
    map: str
    entity: str
    x: float
    y: float
    note: str = ""


class RevealRequest(BaseModel):
    campaign: str
    map: str
    entity: str
    revealed: bool = True
    as_name: str = ""
    at_session: str = ""


@router.get("/maps")
def list_maps(campaign: str) -> dict:
    with read_only_session() as session:
        return {"maps": maps.maps_of(session, slug=campaign)}


@router.post("/map")
def create_map(http: Request, request: MapRequest) -> dict:
    guard(http, request.campaign)
    try:
        with neo4j_session() as session:
            return session.execute_write(lambda tx: maps.create(
                tx, slug=request.campaign, name=request.name,
                place=request.place, asset=request.asset,
                created_at=now_iso()))
    except ValueError as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad


@router.get("/map/pins")
def read_pins(http: Request, campaign: str, map_id: str,
              preview: bool = False) -> dict:
    """What this reader may see on this map.

    THE ONE CHOKE POINT for the map's half of visibility. The route decides the
    audience from the seat and hands `maps.pins` a boolean it computed; the
    client never gets to assert it. Note the shape: the hidden pins are not
    fetched and filtered, they are never selected -- a filter applied after a
    read is one refactor away from being dropped.
    """
    for_player = _for_player(http, campaign, preview)
    with read_only_session() as session:
        pins = maps.pins(session, slug=campaign, map_ref=map_id,
                         for_player=for_player)
    return {"pins": pins, "as_player": for_player}


@router.post("/map/pin")
def pin_entity(http: Request, request: PinRequest) -> dict:
    guard(http, request.campaign)
    try:
        with neo4j_session() as session:
            return session.execute_write(lambda tx: maps.pin(
                tx, slug=request.campaign, map_ref=request.map,
                entity=request.entity, x=request.x, y=request.y,
                note=request.note))
    except ValueError as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad


@router.delete("/map/pin")
def unpin_entity(http: Request, campaign: str, map_id: str,
                 entity: str) -> dict:
    guard(http, campaign)
    with neo4j_session() as session:
        return {"removed": session.execute_write(lambda tx: maps.unpin(
            tx, slug=campaign, map_ref=map_id, entity=entity))}


@router.post("/map/reveal")
def reveal_pin(http: Request, request: RevealRequest) -> dict:
    """Turn a pin face-up, optionally under the name the table knows it by."""
    guard(http, request.campaign)
    try:
        with neo4j_session() as session:
            return {"revealed": session.execute_write(lambda tx: maps.reveal(
                tx, slug=request.campaign, map_ref=request.map,
                entity=request.entity, revealed=request.revealed,
                as_name=request.as_name, at_session=request.at_session))}
    except ValueError as bad:
        raise HTTPException(status_code=404, detail=str(bad)) from bad


# ----------------------------------------------------------- scheduling


class SittingRequest(BaseModel):
    campaign: str
    on: str = ""
    note: str = ""
    sitting: str = ""
    #: `yes`, `no` or `maybe`. Note what is NOT here: who is answering.
    answer: str = ""
    session: str = ""


@router.get("/sittings")
def read_sittings(campaign: str) -> dict:
    """Every proposed evening, with who said what -- and how many never said.

    SILENCE COMES BACK AS ITS OWN NUMBER. "Two said no" and "two have not
    answered" lead to opposite decisions, and a single availability count
    collapses them.
    """
    with read_only_session() as session:
        return {"sittings": scheduling.sittings(session, slug=campaign)}


@router.post("/sitting")
def propose_sitting(http: Request, request: SittingRequest) -> dict:
    guard(http, request.campaign)
    try:
        with neo4j_session() as session:
            return session.execute_write(lambda tx: scheduling.propose(
                tx, slug=request.campaign, on=request.on, note=request.note))
    except ValueError as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad


@router.delete("/sitting")
def withdraw_sitting(http: Request, campaign: str, sitting: str) -> dict:
    guard(http, campaign)
    with neo4j_session() as session:
        return {"withdrawn": session.execute_write(
            lambda tx: scheduling.withdraw(tx, slug=campaign, sitting=sitting))}


@router.post("/sitting/answer")
def answer_sitting(http: Request, request: SittingRequest) -> dict:
    """Say whether you can make it.

    THE ANSWERER COMES FROM THE SEAT, NOT THE BODY. There is no `reader` field
    to fill in, for the same reason the map takes no `asDM` flag: a field a
    client fills in is a field a client can fill in wrongly, and "somebody
    marked me unavailable" is a bug that looks exactly like a scheduling
    disagreement.

    NO `guard` HERE, DELIBERATELY, and it is the one write on this router that
    does not take one -- answering is what a PLAYER is for, and requiring
    ownership would mean only the DM could ever reply. What stops a player
    writing anything else is that this route can only ever set one property on
    one edge, keyed to the reader the gate identified.
    """
    reader = _reader(http)
    if not reader:
        raise HTTPException(
            status_code=401,
            detail="an answer needs somebody to have given it, and this "
                   "deployment has not identified you")
    try:
        with neo4j_session() as session:
            return {"answer": session.execute_write(lambda tx: scheduling.answer(
                tx, slug=request.campaign, sitting=request.sitting,
                reader=reader, says=request.answer))}
    except ValueError as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad


@router.post("/sitting/held")
def hold_session_on(http: Request, request: SittingRequest) -> dict:
    """Record that this session was the one played on that evening."""
    guard(http, request.campaign)
    try:
        with neo4j_session() as session:
            return session.execute_write(lambda tx: scheduling.hold_on(
                tx, slug=request.campaign, session=request.session,
                sitting=request.sitting))
    except ValueError as bad:
        raise HTTPException(status_code=404, detail=str(bad)) from bad


# ------------------------------------------------------------ inventory


class GiveRequest(BaseModel):
    campaign: str
    item: str
    holder: str
    at_session: str = ""
    note: str = ""


@router.get("/inventory")
def read_inventory(campaign: str, holder: str = "") -> dict:
    """What this table is carrying, or what one holder is.

    THE PARTY IS JUST A HOLDER. `hb:<slug>:the-party` is an entity like any
    other, so there is no separate party-inventory route and no second shape
    for a caller to get wrong.
    """
    with read_only_session() as session:
        if holder:
            return {"held": inventory.held_by(session, slug=campaign,
                                              holder=holder)}
        return {"held": inventory.ledger(session, slug=campaign)}


@router.get("/inventory/provenance")
def read_provenance(campaign: str, item: str) -> dict:
    """Every hand this item has passed through. The reason time is a property
    rather than a second graph."""
    with read_only_session() as session:
        return {"held_by": inventory.provenance(session, slug=campaign,
                                                item=item)}


@router.post("/inventory/give")
def give_item(http: Request, request: GiveRequest) -> dict:
    guard(http, request.campaign)
    try:
        with neo4j_session() as session:
            return session.execute_write(lambda tx: inventory.give(
                tx, slug=request.campaign, item=request.item,
                holder=request.holder, at_session=request.at_session,
                note=request.note))
    except ValueError as bad:
        raise HTTPException(status_code=404, detail=str(bad)) from bad


@router.post("/inventory/drop")
def drop_item(http: Request, request: GiveRequest) -> dict:
    """Put it down. The holding CLOSES; it is not deleted -- that the party
    carried the Sunsword for six sessions stays true."""
    guard(http, request.campaign)
    with neo4j_session() as session:
        return {"dropped": session.execute_write(lambda tx: inventory.drop(
            tx, slug=request.campaign, item=request.item,
            holder=request.holder, at_session=request.at_session))}


# --------------------------------------------------------------- images


class PortrayRequest(BaseModel):
    campaign: str
    entity: str
    asset: str
    primary: bool = True


@router.post("/asset/upload")
async def upload_asset(http: Request, campaign: str,
                       file: UploadFile) -> dict:
    """Store a picture a person chose.

    THE ROUTE CANNOT NAME THE ORIGIN. It calls `store_upload`, which can only
    ever stamp `uploaded` -- there is no parameter here to get wrong and no
    request field a client could set to `book`. That is the same rule that
    makes `plane:'canon'` the seed loader's alone.
    """
    guard(http, campaign)
    suffix = IMAGE_TYPES.get(file.content_type or "")
    if suffix is None:
        raise HTTPException(
            status_code=415,
            detail=f"{file.content_type!r} is not an image this store keeps: "
                   f"{sorted(IMAGE_TYPES)}")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="an empty file is not a picture")
    if len(payload) > MAX_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"{len(payload)} bytes is past the {MAX_UPLOAD} limit")

    sha = assets.digest(payload)
    path = assets.path_for(Path(settings.asset_dir), sha, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    # CONTENT-ADDRESSED, so the same picture uploaded twice is one file and
    # re-writing it would only ever write identical bytes.
    if not path.exists():
        path.write_bytes(payload)

    with neo4j_session() as session:
        return session.execute_write(lambda tx: assets.store_upload(
            tx, sha256=sha, media_type=file.content_type, campaign=campaign,
            uploaded_by=_reader(http), created_at=now_iso()))


@router.get("/asset/{asset_id}")
def read_asset(asset_id: str) -> FileResponse:
    """Serve the bytes.

    THE PATH IS DERIVED FROM THE STORED HASH, never from the request. The id
    arrives from a URL, so it is looked up and the hash the GRAPH holds picks
    the file -- an id carrying `../` reaches nothing, because it is a lookup
    key and never a path segment.
    """
    with read_only_session() as session:
        row = session.run(
            "MATCH (a:Asset {id:$id}) RETURN a.sha256 AS sha, "
            "a.media_type AS media_type", {"id": asset_id}).single()
    if row is None or not row["sha"]:
        raise HTTPException(status_code=404, detail=f"no asset {asset_id!r}")
    suffix = IMAGE_TYPES.get(row["media_type"] or "", "")
    path = assets.path_for(Path(settings.asset_dir), row["sha"], suffix)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{asset_id!r} is in the graph but its bytes are gone")
    return FileResponse(
        path,
        media_type=row["media_type"] or mimetypes.guess_type(path.name)[0],
        # A content-addressed URL can never mean different bytes later.
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/portraits")
def read_portraits(entity_id: str, campaign: str) -> dict:
    """Every picture of this entity, each saying where it came from.

    THE CAPTION TRAVELS WITH THE PICTURE. `assets.CAPTION` lives beside the
    property that decides it so the words a DM reads cannot drift from the
    origin they describe.
    """
    with read_only_session() as session:
        found = assets.portraits(session, entity=entity_id, campaign=campaign)
    return {"portraits": [
        {**p, "caption": assets.CAPTION.get(p["origin"], p["origin"])}
        for p in found]}


@router.post("/portray")
def portray_entity(http: Request, request: PortrayRequest) -> dict:
    guard(http, request.campaign)
    with neo4j_session() as session:
        return {"portrayed": session.execute_write(lambda tx: assets.portray(
            tx, entity=request.entity, asset=request.asset,
            campaign=request.campaign, primary=request.primary))}
