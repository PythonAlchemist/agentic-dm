"""Parse Forgotten Realms Wiki content into gazetteer records.

This module is pure: it turns MediaWiki API payloads that somebody else fetched into
plain data. Nothing here opens a socket, calls an LLM, reads a clock or touches Neo4j --
`backend/scripts/harvest_gazetteer.py` does the fetching and passes the fetch date in.

The wiki is third-party content under CC-BY-SA; see `LICENCE` and `ATTRIBUTION`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.graph.schema import CANON_ENTITY_TYPES, EntityType

API_URL = "https://forgottenrealms.fandom.com/api.php"
INDEX_PAGE = "Curse of Strahd"
LICENCE = "CC-BY-SA"
ATTRIBUTION = "Forgotten Realms Wiki (forgottenrealms.fandom.com), text under CC BY-SA"

#: The `==Index==` subsections of the Curse of Strahd page, mapped onto the project's
#: entity vocabulary. Keys are wiki headings, values are `EntityType` members -- never
#: bare strings, so a renamed or removed member breaks here instead of silently
#: producing an entity type the graph does not know about.
INDEX_SECTION_TYPES: dict[str, EntityType] = {
    "Characters": EntityType.NPC,
    "Creatures": EntityType.MONSTER,
    "Items": EntityType.ITEM,
    "Magic": EntityType.ITEM,
    "Locations": EntityType.LOCATION,
    "Organizations": EntityType.FACTION,
    "Miscellaneous": EntityType.LORE,
}

#: Infobox parameters worth keeping. Single-valued ones stay strings; the rest are split.
SINGLE_VALUED_FIELDS = ("name", "occupation")
MULTI_VALUED_FIELDS = (
    "aliases",
    "titles",
    "home",
    "race",
    "parents",
    "spouses",
    "siblings",
    "children",
)
INFOBOX_FIELDS = (*SINGLE_VALUED_FIELDS, *MULTI_VALUED_FIELDS)

# A source book can only contain the canon types. Checked at import so a schema change
# that drops one of them fails loudly here rather than writing an unusable gazetteer.
_NON_CANON = sorted(t.value for t in set(INDEX_SECTION_TYPES.values()) - CANON_ENTITY_TYPES)
if _NON_CANON:  # pragma: no cover - guards a schema edit, not a runtime path
    raise RuntimeError(f"INDEX_SECTION_TYPES maps to non-canon entity types: {_NON_CANON}")

# An infobox is lead content: it sits above the first section heading. Anything further
# down that happens to look like one (`{{Appearances}}`) is not an infobox, and a page
# with nothing above the first heading simply has none.
_HEADING = re.compile(r"^==", re.M)
_P_TEMPLATE = re.compile(r"\{\{P\|(.*?)\}\}")
_LINK = re.compile(r"\[\[([^\[\]]+)\]\]")
_REF = re.compile(r"<ref[^>]*?/>|<ref[^>]*?>.*?</ref>", re.S | re.I)
_LINE_BREAK = re.compile(r"<br\s*/?>", re.I)
_HTML_TAG = re.compile(r"<[^>]+>")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_REDIRECT = re.compile(r"\s*#redirect\s*:?\s*\[\[([^\]]+)\]\]", re.I)
_COS_CITE = re.compile(r"\{\{Cite book/Curse of Strahd\s*(\|[^{}]*)?\}\}", re.I)
_MIN_INFOBOX_PARAMS = 3


@dataclass(frozen=True)
class IndexEntry:
    """One `{{P|[[target|display]]|pages}}` row of the wiki's Curse of Strahd index."""

    target: str
    display: str | None
    entity_type: EntityType
    category: str
    subcategory: str | None
    index_pages: str | None


@dataclass(frozen=True)
class WikiPage:
    """One page as the `action=query&prop=revisions` API returned it."""

    title: str
    exists: bool
    wikitext: str = ""
    redirect_to: str | None = None
    infobox: dict[str, str] = field(default_factory=dict)


def split_top_level(text: str, separator: str = "|") -> list[str]:
    """Split on `separator` occurrences that are not nested inside `[[…]]` or `{{…}}`.

    Infobox values routinely contain `[[Target|display]]`, so a naive `split("|")`
    corrupts them -- the same goes for commas inside a piped link's display text.
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        pair = text[i : i + 2]
        if pair in ("[[", "{{"):
            depth += 1
            buf.append(pair)
            i += 2
            continue
        if pair in ("]]", "}}"):
            depth = max(0, depth - 1)
            buf.append(pair)
            i += 2
            continue
        if depth == 0 and text.startswith(separator, i):
            parts.append("".join(buf))
            buf = []
            i += len(separator)
            continue
        buf.append(text[i])
        i += 1
    parts.append("".join(buf))
    return parts


def strip_markup(value: str) -> str:
    """Reduce an infobox value to plain text: links to their display form, refs dropped."""
    text = _REF.sub("", value)
    previous = None
    while previous != text:  # templates nest; peel innermost-first until none remain
        previous = text
        text = _TEMPLATE.sub("", text)
    previous = None
    while previous != text:
        previous = text
        text = _LINK.sub(lambda m: split_top_level(m.group(1))[-1], text)
    text = _HTML_TAG.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", text).strip()


def split_values(value: str) -> list[str]:
    """Split a multi-valued infobox field into cleaned, de-duplicated values.

    Real pages separate values with commas *and* with `<br/>`, so both count. References
    go first because their page ranges (`|11-12,181,221`) are full of commas.
    """
    text = _LINE_BREAK.sub(",", _REF.sub("", value))
    values: list[str] = []
    for part in split_top_level(text, ","):
        cleaned = strip_markup(part)
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def _section_bodies(wikitext: str, level: int) -> list[tuple[str, str]]:
    """Return (heading, body) for each heading at `level`.

    A body runs to the next heading of the same or higher rank, so a `==Index==` body
    keeps its `===Characters===` subsections instead of stopping at the first of them.
    """
    marks = "=" * level
    heading = re.compile(rf"^{marks}(?!=)\s*(.+?)\s*{marks}\s*$", re.M)
    terminator = re.compile(rf"^={{2,{level}}}(?!=)", re.M)
    sections: list[tuple[str, str]] = []
    for match in heading.finditer(wikitext):
        rest = wikitext[match.end() :]
        following = terminator.search(rest)
        sections.append((match.group(1), rest[: following.start()] if following else rest))
    return sections


def _top_level_templates(text: str) -> list[str]:
    """Return the contents of each brace-balanced template that is not nested in another."""
    templates: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(text):
        if text.startswith("{{", i):
            if depth == 0:
                start = i
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                templates.append(text[start + 2 : i - 2])
            continue
        i += 1
    return templates


def _named_params(template_body: str) -> dict[str, str]:
    """Parse `key = value` parameters of a template body, ignoring positional ones."""
    params: dict[str, str] = {}
    for part in split_top_level(template_body)[1:]:
        key, sep, value = part.partition("=")
        if not sep or "[[" in key or "{{" in key or "\n" in key.strip():
            continue
        params[key.strip()] = value.strip()
    return params


def parse_index(wikitext: str) -> list[IndexEntry]:
    """Read the `==Index==` section of the Curse of Strahd page.

    Subsections outside `INDEX_SECTION_TYPES` (`===Trivia===`, `===Connections===`) are
    not entity categories and are skipped rather than guessed at.
    """
    index_section = ""
    for title, body in _section_bodies(wikitext, 2):
        if title.strip().lower() == "index":
            index_section = body
            break

    entries: list[IndexEntry] = []
    for category, body in _section_bodies(index_section, 3):
        entity_type = INDEX_SECTION_TYPES.get(category)
        if entity_type is None:
            continue
        for template in _top_level_templates(body):
            subcategory = _named_params(template).get("title") or None
            for row in _P_TEMPLATE.findall(template):
                entry = _parse_index_row(row, entity_type, category, subcategory)
                if entry is not None:
                    entries.append(entry)
    return entries


def _parse_index_row(
    row: str, entity_type: EntityType, category: str, subcategory: str | None
) -> IndexEntry | None:
    fields = split_top_level(row)
    link = _LINK.search(fields[0])
    if link is None:
        return None
    parts = split_top_level(link.group(1))
    target = parts[0].strip()
    display = parts[-1].strip() if len(parts) > 1 else None
    pages = strip_markup(fields[1]) if len(fields) > 1 else None
    return IndexEntry(
        target=target,
        display=display if display and display != target else None,
        entity_type=entity_type,
        category=category,
        subcategory=subcategory,
        index_pages=pages or None,
    )


def parse_infobox(wikitext: str) -> dict[str, str]:
    """Return the raw parameters of a page's lead infobox template.

    Maintenance templates (`{{Otheruses4|…}}`, `{{Split|…}}`) sit above the infobox but
    carry positional arguments, so "the first lead template with several named
    parameters" picks the infobox out without a hardcoded list of template names.
    """
    heading = _HEADING.search(wikitext)
    lead = wikitext[: heading.start()] if heading else wikitext
    for template in _top_level_templates(lead):
        params = _named_params(template)
        if len(params) >= _MIN_INFOBOX_PARAMS:
            return params
    return {}


def parse_redirect(wikitext: str) -> str | None:
    """Return the target of a `#REDIRECT [[…]]` page, or None if it is not one."""
    match = _REDIRECT.match(wikitext)
    if match is None:
        return None
    return split_top_level(match.group(1))[0].split("#")[0].strip()


def parse_cited_pages(basicrefs: str) -> list[str]:
    """Pull Curse of Strahd page citations out of an infobox `basicrefs` value.

    `{{Cite book/Curse of Strahd|45-46}}` cites pages 45-46; citations of other books
    are somebody else's page numbering and are dropped.
    """
    pages: list[str] = []
    for args in _COS_CITE.findall(basicrefs):
        fields = split_top_level(args.lstrip("|"))
        cited = fields[0].strip() if fields else ""
        if cited and cited not in pages:
            pages.append(cited)
    return pages


def parse_pages_response(payload: dict) -> dict[str, WikiPage]:
    """Turn one batched `action=query` response into pages keyed by *requested* title.

    MediaWiki normalises titles it was asked for (`bag of tricks` -> `Bag of tricks`),
    so the response is re-keyed by the title the caller asked about; otherwise the join
    back onto the index silently loses every entry the wiki capitalised.
    """
    query = payload.get("query", {})
    requested_by_returned = {n["to"]: n["from"] for n in query.get("normalized", [])}
    pages: dict[str, WikiPage] = {}
    for page in query.get("pages", []):
        title = page.get("title", "")
        key = requested_by_returned.get(title, title)
        if page.get("missing") or page.get("invalid"):
            pages[key] = WikiPage(title=title, exists=False)
            continue
        revisions = page.get("revisions") or [{}]
        wikitext = revisions[0].get("slots", {}).get("main", {}).get("content", "")
        redirect_to = parse_redirect(wikitext)
        pages[key] = WikiPage(
            title=title,
            exists=True,
            wikitext=wikitext,
            redirect_to=redirect_to,
            infobox={} if redirect_to else parse_infobox(wikitext),
        )
    return pages


def _entry_aliases(index_entry: IndexEntry, infobox: dict[str, str]) -> list[str]:
    """Recorded aliases only: the index's display form and the infobox `aliases` field.

    Nothing inferred. `titles` ("Lord", "Duchess of Daggerford") and the `othernames`
    used by non-person infoboxes are captured as data but are not alias keys -- matching
    a candidate on a bare honorific is exactly the junk-laundering to avoid.
    """
    aliases: list[str] = []
    candidates = [index_entry.display or ""] + split_values(infobox.get("aliases", ""))
    for alias in candidates:
        if alias and alias != index_entry.target and alias not in aliases:
            aliases.append(alias)
    return aliases


def build_document(
    index_entries: list[IndexEntry],
    pages: dict[str, WikiPage],
    fetch_date: str,
) -> dict:
    """Assemble the gazetteer document written to `data/gazetteer/curse-of-strahd.json`."""
    entries: list[dict] = []
    for index_entry in index_entries:
        page = pages.get(index_entry.target)
        infobox = page.infobox if page else {}
        fields: dict[str, list[str] | str] = {}
        for name in INFOBOX_FIELDS:
            raw = infobox.get(name, "")
            value = strip_markup(raw) if name in SINGLE_VALUED_FIELDS else split_values(raw)
            if value:
                fields[name] = value
        entries.append(
            {
                "name": index_entry.target,
                "aliases": _entry_aliases(index_entry, infobox),
                "entity_type": index_entry.entity_type.value,
                "wiki_category": index_entry.category,
                "wiki_subcategory": index_entry.subcategory,
                "fetched": page is not None,
                "page_exists": bool(page and page.exists),
                "redirect_to": page.redirect_to if page else None,
                "index_pages": index_entry.index_pages,
                "cited_pages": parse_cited_pages(infobox.get("basicrefs", "")),
                "fields": fields,
            }
        )
    return {
        "source": {
            "api_url": API_URL,
            "index_page": INDEX_PAGE,
            "fetched": fetch_date,
            "licence": LICENCE,
            "attribution": ATTRIBUTION,
        },
        "counts": {
            "entries": len(entries),
            "fetched": sum(1 for e in entries if e["fetched"]),
            "page_exists": sum(1 for e in entries if e["page_exists"]),
            "redlinks": sum(1 for e in entries if e["fetched"] and not e["page_exists"]),
            "redirects": sum(1 for e in entries if e["redirect_to"]),
        },
        "entries": entries,
    }
