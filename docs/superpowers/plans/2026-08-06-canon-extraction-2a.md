# Canon Extraction 2a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn transcribed Curse of Strahd chapters into scored candidate entities and relationships, so extraction quality can be measured against the Village of Barovia golden set before anything reaches the graph.

**Architecture:** Four units. `sections.py` splits chapter markdown on `##` headings and packs contiguous sections into token-budgeted extraction units — pure text. `extract.py` runs three per-layer LLM passes over each unit and returns name-keyed candidates. `grade.py` scores a candidate set against a golden subset — pure. A CLI drives the tune loop. Three of the four have no external dependency, which is where the test leverage sits.

**Tech Stack:** Python 3.12, `tiktoken` for budgeting, OpenAI `gpt-4o-mini` via `AsyncOpenAI`, pytest + pytest-asyncio.

## Global Constraints

- Python `>=3.12`. Builtin generics (`list[str]`, `str | None`), never `typing.List`.
- Ruff: `line-length = 100`, `target-version = "py312"`, rules `["E", "F", "I", "UP"]`.
- Async tests require an explicit `@pytest.mark.asyncio` decorator (pytest-asyncio 1.3.0, strict mode).
- Tests touching Neo4j carry `@pytest.mark.neo4j` — **no task here needs Neo4j**.
- **Nothing in 2a writes to Neo4j.** Output is a candidate set plus a score.
- **Candidates carry names, not ids.** Id minting and cross-chapter dedup are 2b.
- Extraction model is `gpt-4o-mini`. Layer vocabularies come from `LAYER_MAP`, never re-listed in prompt literals.
- No live API calls in tests; the OpenAI client is always mocked.
- `data/` is gitignored.

## Existing interfaces this builds on

```python
# backend/canon/models.py
@dataclass
class Chapter:
    slug: str; title: str; start_page: int; end_page: int; markdown: str

# backend/canon/assembler.py
def assemble_chapters(transcripts: list[PageTranscript]) -> list[Chapter]
def slugify(title: str) -> str

# backend/canon/seed_loader.py
SEED_DIR: Path
def extractable_subset(data: dict, source: str = "ch3") -> dict   # {"nodes": [...], "edges": [...]}

# backend/graph/schema.py
class Layer(str, Enum): SPATIAL = "spatial"; SOCIAL = "social"; NARRATIVE = "narrative"
LAYER_MAP: dict[RelationshipType, Layer | None]     # total over 37 members
```

Layer vocabularies, derived from `LAYER_MAP` (do not hardcode):
- **spatial** (4): `CONNECTED_TO`, `CONTAINS`, `LOCATED_IN`, `TRAVELED_TO`
- **social** (10): `ALLIED_WITH`, `ENEMY_OF`, `GUARDS`, `HOSTILE_TO`, `KNOWS`, `MEMBER_OF`, `OWNS`, `RELATED_TO`, `SERVES`, `WIELDS`
- **narrative** (9): `COMPLETED`, `GAVE_QUEST`, `IDENTITY_OF`, `OBJECTIVE_AT`, `OPPOSES`, `PREREQUISITE_OF`, `RESOLVES_TO`, `SEEKS`, `THREATENS`

---

## File Structure

**Created:**
- `backend/canon/sections.py` — `split_sections`, `pack_sections`
- `backend/canon/extract.py` — `CandidateExtractor`, the layer prompts
- `backend/canon/grade.py` — `grade`, `normalize_name`
- `backend/scripts/extract_canon.py` — CLI
- `tests/test_canon/test_sections.py`
- `tests/test_canon/test_extract.py`
- `tests/test_canon/test_grade.py`

**Modified:**
- `backend/canon/models.py` — add `Section`, `ExtractionUnit`, `CandidateNode`, `CandidateEdge`, `GradeReport`

---

### Task 1: Models and section splitting

**Files:**
- Modify: `backend/canon/models.py`
- Create: `backend/canon/sections.py`
- Create: `tests/test_canon/test_sections.py`

**Interfaces:**
- Consumes: `Chapter` from `backend/canon/models.py`
- Produces:
  - `Section(chapter_slug: str, chapter_title: str, heading: str, index: int, markdown: str)`
  - `ExtractionUnit(chapter_slug: str, chapter_title: str, headings: list[str], markdown: str, token_count: int)`
  - `split_sections(chapter: Chapter) -> list[Section]`
  - `pack_sections(sections: list[Section], max_tokens: int = 1500) -> list[ExtractionUnit]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_sections.py`:

```python
"""Splitting a chapter into extraction units.

Chapters are too big to extract in one pass (chapter 4 is ~36k tokens) and
ChromaDB chunks split mid-topic, so an entity introduced in one and located in
the next becomes two partial extractions. Sections split on the seams the book's
own author chose.
"""

import pytest

from backend.canon.models import Chapter
from backend.canon.sections import pack_sections, split_sections


def chapter(markdown: str) -> Chapter:
    return Chapter(
        slug="chapter-3-the-village-of-barovia",
        title="Chapter 3: The Village of Barovia",
        start_page=80,
        end_page=94,
        markdown=markdown,
    )


class TestSplitSections:
    def test_splits_on_h2_headings(self):
        sections = split_sections(
            chapter("# Chapter 3\n\nIntro.\n\n## Area E1\n\nShop.\n\n## Area E2\n\nTavern.")
        )

        assert [s.heading for s in sections] == ["(preamble)", "Area E1", "Area E2"]
        assert "Shop." in sections[1].markdown

    def test_preamble_captures_text_before_the_first_heading(self):
        sections = split_sections(chapter("# Chapter 3\n\nIntro prose.\n\n## Area E1\n\nShop."))

        assert sections[0].heading == "(preamble)"
        assert "Intro prose." in sections[0].markdown

    def test_no_preamble_section_when_chapter_opens_on_a_heading(self):
        sections = split_sections(chapter("## Area E1\n\nShop.\n\n## Area E2\n\nTavern."))

        assert [s.heading for s in sections] == ["Area E1", "Area E2"]

    def test_h3_does_not_split(self):
        """Sub-headings belong with their section, not beside it."""
        sections = split_sections(
            chapter("## Area E1\n\nShop.\n\n### Wares\n\nOverpriced.\n\n## Area E2\n\nTavern.")
        )

        assert len(sections) == 2
        assert "Overpriced." in sections[0].markdown

    def test_carries_chapter_provenance(self):
        sections = split_sections(chapter("## Area E1\n\nShop."))

        assert sections[0].chapter_slug == "chapter-3-the-village-of-barovia"
        assert sections[0].chapter_title == "Chapter 3: The Village of Barovia"
        assert sections[0].index == 0

    def test_empty_chapter_yields_nothing(self):
        assert split_sections(chapter("   \n\n  ")) == []


class TestPackSections:
    def test_small_sections_combine(self):
        sections = split_sections(
            chapter("## A\n\nshort.\n\n## B\n\nshort.\n\n## C\n\nshort.")
        )
        units = pack_sections(sections, max_tokens=1500)

        assert len(units) == 1
        assert units[0].headings == ["A", "B", "C"]

    def test_oversized_section_stands_alone(self):
        big = "word " * 3000
        sections = split_sections(chapter(f"## Small\n\ntiny.\n\n## Big\n\n{big}"))
        units = pack_sections(sections, max_tokens=1500)

        assert len(units) == 2
        assert units[0].headings == ["Small"]
        assert units[1].headings == ["Big"]
        assert units[1].token_count > 1500

    def test_packing_loses_no_section(self):
        sections = split_sections(
            chapter("".join(f"## S{i}\n\n{'word ' * 200}\n\n" for i in range(10)))
        )
        units = pack_sections(sections, max_tokens=1500)

        packed = [h for u in units for h in u.headings]
        assert packed == [s.heading for s in sections]

    def test_packing_duplicates_no_section(self):
        sections = split_sections(
            chapter("".join(f"## S{i}\n\n{'word ' * 200}\n\n" for i in range(10)))
        )
        units = pack_sections(sections, max_tokens=1500)

        packed = [h for u in units for h in u.headings]
        assert len(packed) == len(set(packed))

    def test_units_carry_their_token_count(self):
        units = pack_sections(split_sections(chapter("## A\n\nsome words here.")))

        assert units[0].token_count > 0

    def test_empty_input_yields_no_units(self):
        assert pack_sections([]) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_canon/test_sections.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon.sections'`

- [ ] **Step 3: Add the models**

Append to `backend/canon/models.py`:

```python
@dataclass
class Section:
    """One `##` section of a chapter, with its chapter provenance."""

    chapter_slug: str
    chapter_title: str
    heading: str
    index: int
    markdown: str


@dataclass
class ExtractionUnit:
    """One or more contiguous sections, sized to fit a single extraction pass."""

    chapter_slug: str
    chapter_title: str
    headings: list[str]
    markdown: str
    token_count: int


@dataclass
class CandidateNode:
    """A proposed canon entity, identified by name -- ids are minted in stage 2b."""

    name: str
    entity_type: str
    description: str = ""
    layer: str = ""
    chapter_slug: str = ""
    section_heading: str = ""


@dataclass
class CandidateEdge:
    """A proposed relationship between two candidate nodes, by name."""

    source_name: str
    target_name: str
    rel_type: str
    evidence: str = ""
    layer: str = ""
    chapter_slug: str = ""
    section_heading: str = ""


@dataclass
class GradeReport:
    """Recall against a golden subset, plus what to look at by hand.

    Precision is deliberately absent: the golden set is not exhaustive, so an
    unmatched candidate is usually a legitimate entity the key omits rather than
    a fabrication. Scoring it would punish thoroughness.
    """

    node_recall: float
    edge_recall: float
    missing_nodes: list[str]
    missing_edges: list[str]
    unmatched_nodes: list[str]
    unmatched_edges: list[str]
```

- [ ] **Step 4: Implement splitting and packing**

Create `backend/canon/sections.py`:

```python
"""Split a chapter into units small enough to extract from in one pass.

A whole chapter is too large -- Castle Ravenloft is ~36k tokens, and a single
response enumerating its entities would be unmanageable. ChromaDB chunks are the
wrong unit too: they split mid-topic, so an entity introduced in one chunk and
located in the next becomes two partial extractions that the least-certain part
of the pipeline has to merge. Sections split where the book's own author put a
heading, which mostly keeps related facts together.
"""

import re

import tiktoken

from backend.canon.models import Chapter, ExtractionUnit, Section

# H2 only. An H3 sub-heading belongs with its section rather than beside it.
_H2 = re.compile(r"^##\s+(?!#)(.+?)\s*$", re.MULTILINE)

PREAMBLE_HEADING = "(preamble)"
DEFAULT_MAX_TOKENS = 1500

_encoder = tiktoken.encoding_for_model("gpt-4")


def _count(text: str) -> int:
    return len(_encoder.encode(text))


def split_sections(chapter: Chapter) -> list[Section]:
    """Split a chapter's markdown on its `##` headings.

    Text before the first heading becomes a `(preamble)` section, since chapter
    introductions carry real content and would otherwise be dropped.
    """
    if not chapter.markdown.strip():
        return []

    matches = list(_H2.finditer(chapter.markdown))
    pieces: list[tuple[str, str]] = []

    first_start = matches[0].start() if matches else len(chapter.markdown)
    preamble = chapter.markdown[:first_start].strip()
    if preamble:
        pieces.append((PREAMBLE_HEADING, preamble))

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(chapter.markdown)
        body = chapter.markdown[match.start():end].strip()
        pieces.append((match.group(1).strip(), body))

    return [
        Section(
            chapter_slug=chapter.slug,
            chapter_title=chapter.title,
            heading=heading,
            index=i,
            markdown=body,
        )
        for i, (heading, body) in enumerate(pieces)
    ]


def pack_sections(
    sections: list[Section],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[ExtractionUnit]:
    """Group contiguous sections into units under a token budget.

    Section sizes vary by two orders of magnitude, so one-call-per-section would
    waste calls on 14-token stubs. A section larger than the budget stands alone
    rather than being split -- splitting mid-section is what this design avoids.
    """
    units: list[ExtractionUnit] = []
    batch: list[Section] = []
    batch_tokens = 0

    def flush() -> None:
        nonlocal batch, batch_tokens
        if not batch:
            return
        units.append(
            ExtractionUnit(
                chapter_slug=batch[0].chapter_slug,
                chapter_title=batch[0].chapter_title,
                headings=[s.heading for s in batch],
                markdown="\n\n".join(s.markdown for s in batch),
                token_count=batch_tokens,
            )
        )
        batch = []
        batch_tokens = 0

    for section in sections:
        tokens = _count(section.markdown)
        if batch and batch_tokens + tokens > max_tokens:
            flush()
        batch.append(section)
        batch_tokens += tokens
        if batch_tokens >= max_tokens:
            flush()

    flush()
    return units
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_sections.py -v`
Expected: 13 passed

- [ ] **Step 6: Check against the real corpus**

Run:

```bash
uv run python -c "
from backend.canon.page_extractor import PageExtractor
from backend.canon.cache import TranscriptCache
from backend.canon.assembler import assemble_chapters
from backend.canon.sections import split_sections, pack_sections
from backend.core.config import settings

cache = TranscriptCache(settings.canon_dir / 'cos')
ex = PageExtractor('data/cos.pdf')
ts = [t for p in ex.extract() if (t := cache.get(p.page_number, p.sha256))]
ex.close()
for c in assemble_chapters(ts):
    if c.title.startswith(('Chapter 3', 'Chapter 4', 'Appendix D')):
        s = split_sections(c); u = pack_sections(s)
        print(f'{c.title[:34]:36} {len(s):3} sections -> {len(u):3} units, '
              f'max {max(x.token_count for x in u):5} tokens')
"
```

Expected: chapter 3 a handful of units, chapter 4 far more, Appendix D somewhere between,
and every max under ~4,000 tokens except where a single section genuinely exceeds it.
Report the actual numbers — they set expectations for extraction cost.

- [ ] **Step 7: Commit**

```bash
git add backend/canon/models.py backend/canon/sections.py tests/test_canon/test_sections.py
git commit -m "feat(canon): split chapters into token-budgeted extraction units"
```

---

### Task 2: Grading harness

Built before extraction so the target is defined before anything aims at it.

**Files:**
- Create: `backend/canon/grade.py`
- Create: `tests/test_canon/test_grade.py`

**Interfaces:**
- Consumes: `CandidateNode`, `CandidateEdge`, `GradeReport` (Task 1); `extractable_subset` from `backend/canon/seed_loader.py`
- Produces:
  - `normalize_name(name: str) -> str`
  - `grade(nodes: list[CandidateNode], edges: list[CandidateEdge], golden: dict) -> GradeReport`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_grade.py`:

```python
"""Scoring candidates against the golden set.

Recall is computable; precision is not. The golden set lists 18 nodes for
chapter 3, but the chapter contains far more nameable things, so an unmatched
candidate is usually a legitimate entity the key omits. Scoring precision here
would punish an extractor for being thorough.
"""

from backend.canon.grade import grade, normalize_name
from backend.canon.models import CandidateEdge, CandidateNode


def golden(nodes=None, edges=None) -> dict:
    return {"nodes": nodes or [], "edges": edges or []}


def gnode(name, entity_type="NPC", **kw):
    return {"id": f"cos:npc:{name.lower()}", "name": name, "entity_type": entity_type, **kw}


def gedge(source, target, rel_type):
    return {"source": source, "target": target, "type": rel_type}


def cnode(name, entity_type="NPC"):
    return CandidateNode(name=name, entity_type=entity_type)


def cedge(source, target, rel_type):
    return CandidateEdge(source_name=source, target_name=target, rel_type=rel_type)


class TestNormalizeName:
    def test_case_and_punctuation_are_ignored(self):
        assert normalize_name("Ismark the Lesser") == normalize_name("ismark the lesser")
        assert normalize_name("Bildrath's Mercantile") == normalize_name("Bildraths Mercantile")

    def test_leading_article_is_dropped(self):
        assert normalize_name("The Village of Barovia") == normalize_name("Village of Barovia")

    def test_whitespace_is_collapsed(self):
        assert normalize_name("Blood  on   the Vine") == normalize_name("Blood on the Vine")


class TestNodeRecall:
    def test_perfect_extraction_scores_one(self):
        g = golden(nodes=[gnode("Ireena"), gnode("Ismark")])
        report = grade([cnode("Ireena"), cnode("Ismark")], [], g)

        assert report.node_recall == 1.0
        assert report.missing_nodes == []

    def test_one_miss_of_four_scores_exactly_three_quarters(self):
        g = golden(nodes=[gnode(n) for n in ("A", "B", "C", "D")])
        report = grade([cnode(n) for n in ("A", "B", "C")], [], g)

        assert report.node_recall == 0.75
        assert report.missing_nodes == ["D"]

    def test_alias_counts_as_a_match(self):
        """An extractor that says "Ismark" should not be marked wrong because the
        key says "Ismark Kolyanovich"."""
        g = golden(nodes=[gnode("Ismark Kolyanovich", aliases=["Ismark the Lesser"])])
        report = grade([cnode("Ismark the Lesser")], [], g)

        assert report.node_recall == 1.0

    def test_unmatched_candidates_are_listed_not_scored(self):
        g = golden(nodes=[gnode("Ireena")])
        report = grade([cnode("Ireena"), cnode("A Barkeep")], [], g)

        assert report.node_recall == 1.0, "an extra candidate must not reduce recall"
        assert report.unmatched_nodes == ["A Barkeep"]

    def test_empty_golden_scores_one_not_zero_division(self):
        report = grade([cnode("Ireena")], [], golden())

        assert report.node_recall == 1.0
        assert report.unmatched_nodes == ["Ireena"]


class TestEdgeRecall:
    def test_edge_matches_on_type_and_both_endpoints(self):
        g = golden(edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
                   nodes=[gnode("A"), gnode("B")])
        report = grade([], [cedge("A", "B", "KNOWS")], g)

        assert report.edge_recall == 1.0

    def test_wrong_type_is_not_a_match(self):
        g = golden(edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
                   nodes=[gnode("A"), gnode("B")])
        report = grade([], [cedge("A", "B", "SEEKS")], g)

        assert report.edge_recall == 0.0
        assert len(report.missing_edges) == 1

    def test_reversed_direction_is_not_a_match(self):
        g = golden(edges=[gedge("cos:npc:a", "cos:npc:b", "KNOWS")],
                   nodes=[gnode("A"), gnode("B")])
        report = grade([], [cedge("B", "A", "KNOWS")], g)

        assert report.edge_recall == 0.0


class TestAgainstTheRealSeed:
    def test_grades_against_the_chapter_three_subset(self):
        import yaml

        from backend.canon.seed_loader import SEED_DIR, extractable_subset

        data = yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())
        subset = extractable_subset(data, "ch3")
        report = grade([], [], subset)

        assert report.node_recall == 0.0
        assert len(report.missing_nodes) == len(subset["nodes"])
        assert "Ireena Kolyana" in report.missing_nodes
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_canon/test_grade.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon.grade'`

- [ ] **Step 3: Implement**

Create `backend/canon/grade.py`:

```python
"""Score extracted candidates against a hand-authored golden subset.

Recall is reported as a number. Precision is deliberately not: the golden set is
not exhaustive -- chapter 3 contains far more nameable things than the 18 nodes
the key lists -- so a candidate with no match is usually a legitimate entity the
key omits rather than a fabrication. Scoring it would punish an extractor for
being thorough and reward one for being timid.

Unmatched candidates are therefore listed for human spot-check, never scored.
"""

import re

from backend.canon.models import CandidateEdge, CandidateNode, GradeReport

_PUNCT = re.compile(r"[^a-z0-9 ]")
_ARTICLE = re.compile(r"^(the|a|an) ")
_SPACE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Fold a name for comparison.

    Deliberately loose. Strict matching would fail on "Ismark" versus "Ismark the
    Lesser" and turn recall into a measure of naming luck rather than extraction
    quality. Canonical naming is decided in stage 2b, not here.
    """
    folded = _PUNCT.sub("", name.lower())
    folded = _SPACE.sub(" ", folded).strip()
    return _ARTICLE.sub("", folded)


def _golden_node_names(entry: dict) -> set[str]:
    """Every name a candidate may legitimately use for this golden node."""
    names = {entry.get("name", "")}
    names.update(entry.get("aliases", []) or [])
    return {normalize_name(n) for n in names if n}


def grade(
    nodes: list[CandidateNode],
    edges: list[CandidateEdge],
    golden: dict,
) -> GradeReport:
    """Score candidates against a golden subset."""
    golden_nodes = golden.get("nodes", [])
    golden_edges = golden.get("edges", [])

    # id -> the set of acceptable normalized names, so edges can resolve endpoints
    by_id = {n["id"]: _golden_node_names(n) for n in golden_nodes}

    candidate_names = {normalize_name(c.name) for c in nodes}

    missing_nodes: list[str] = []
    matched_names: set[str] = set()
    for entry in golden_nodes:
        acceptable = _golden_node_names(entry)
        hit = acceptable & candidate_names
        if hit:
            matched_names |= hit
        else:
            missing_nodes.append(entry.get("name", entry["id"]))

    unmatched_nodes = [c.name for c in nodes if normalize_name(c.name) not in matched_names]

    candidate_edges = {
        (normalize_name(e.source_name), normalize_name(e.target_name), e.rel_type)
        for e in edges
    }

    missing_edges: list[str] = []
    matched_edges: set[tuple[str, str, str]] = set()
    for entry in golden_edges:
        sources = by_id.get(entry["source"], set())
        targets = by_id.get(entry["target"], set())
        hits = {
            (s, t, entry["type"])
            for s in sources
            for t in targets
            if (s, t, entry["type"]) in candidate_edges
        }
        if hits:
            matched_edges |= hits
        else:
            missing_edges.append(f"{entry['source']} -{entry['type']}-> {entry['target']}")

    unmatched_edges = [
        f"{e.source_name} -{e.rel_type}-> {e.target_name}"
        for e in edges
        if (normalize_name(e.source_name), normalize_name(e.target_name), e.rel_type)
        not in matched_edges
    ]

    return GradeReport(
        node_recall=_recall(len(golden_nodes) - len(missing_nodes), len(golden_nodes)),
        edge_recall=_recall(len(golden_edges) - len(missing_edges), len(golden_edges)),
        missing_nodes=missing_nodes,
        missing_edges=missing_edges,
        unmatched_nodes=unmatched_nodes,
        unmatched_edges=unmatched_edges,
    )


def _recall(hits: int, total: int) -> float:
    """An empty golden set scores 1.0: nothing was asked for, nothing was missed."""
    return 1.0 if total == 0 else hits / total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_grade.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add backend/canon/grade.py tests/test_canon/test_grade.py
git commit -m "feat(canon): add recall grading against the golden subset"
```

---

### Task 3: Layer extraction

**Files:**
- Create: `backend/canon/extract.py`
- Create: `tests/test_canon/test_extract.py`

**Interfaces:**
- Consumes: `ExtractionUnit`, `CandidateNode`, `CandidateEdge` (Task 1); `Layer`, `LAYER_MAP` from `backend/graph/schema.py`; `EntityType` from `backend/graph/schema.py`
- Produces:
  - `layer_vocabulary(layer: Layer) -> list[str]`
  - `CandidateExtractor(client=None, model: str | None = None, concurrency: int = 6)` with `async .extract_unit(unit, layer) -> tuple[list[CandidateNode], list[CandidateEdge]]` and `async .extract_units(units, layers=None) -> tuple[list[CandidateNode], list[CandidateEdge]]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_extract.py`:

```python
"""Per-layer candidate extraction.

Each pass sees only its own layer's vocabulary. A spatial pass that knows only
about containment produces markedly cleaner output than one prompt asked to find
everything, and it makes a bad layer diagnosable in isolation.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.canon.extract import CandidateExtractor, layer_vocabulary
from backend.canon.models import ExtractionUnit
from backend.graph.schema import Layer


def unit(markdown: str = "## E1\n\nBildrath sells overpriced rope.") -> ExtractionUnit:
    return ExtractionUnit(
        chapter_slug="chapter-3-the-village-of-barovia",
        chapter_title="Chapter 3: The Village of Barovia",
        headings=["E1"],
        markdown=markdown,
        token_count=12,
    )


def make_client(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


class TestLayerVocabulary:
    def test_derives_from_layer_map_not_a_literal(self):
        """Adding a relationship type must not silently leave the extractor blind."""
        spatial = layer_vocabulary(Layer.SPATIAL)

        assert set(spatial) == {"CONNECTED_TO", "CONTAINS", "LOCATED_IN", "TRAVELED_TO"}

    def test_narrative_includes_the_new_types(self):
        narrative = layer_vocabulary(Layer.NARRATIVE)

        for expected in ("SEEKS", "OPPOSES", "IDENTITY_OF", "RESOLVES_TO"):
            assert expected in narrative

    def test_layers_do_not_overlap(self):
        vocabs = [set(layer_vocabulary(l)) for l in Layer]

        assert not vocabs[0] & vocabs[1]
        assert not vocabs[1] & vocabs[2]
        assert not vocabs[0] & vocabs[2]


class TestExtractUnit:
    @pytest.mark.asyncio
    async def test_parses_nodes_and_edges(self):
        client = make_client(
            {
                "nodes": [{"name": "Bildrath", "entity_type": "NPC",
                           "description": "The shopkeeper."}],
                "edges": [{"source_name": "Bildrath", "target_name": "E1",
                           "rel_type": "OWNS", "evidence": "sells rope"}],
            }
        )
        nodes, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes[0].name == "Bildrath"
        assert edges[0].rel_type == "OWNS"

    @pytest.mark.asyncio
    async def test_stamps_provenance_on_every_candidate(self):
        client = make_client(
            {
                "nodes": [{"name": "Bildrath", "entity_type": "NPC"}],
                "edges": [{"source_name": "Bildrath", "target_name": "E1",
                           "rel_type": "OWNS"}],
            }
        )
        nodes, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes[0].chapter_slug == "chapter-3-the-village-of-barovia"
        assert nodes[0].section_heading == "E1"
        assert nodes[0].layer == "social"
        assert edges[0].layer == "social"

    @pytest.mark.asyncio
    async def test_prompt_carries_only_its_own_layer_vocabulary(self):
        client = make_client({"nodes": [], "edges": []})
        await CandidateExtractor(client=client).extract_unit(unit(), Layer.SPATIAL)

        prompt = json.dumps(client.chat.completions.create.call_args.kwargs["messages"])
        assert "CONTAINS" in prompt
        assert "SEEKS" not in prompt, "a spatial pass must not see narrative types"

    @pytest.mark.asyncio
    async def test_edges_of_the_wrong_layer_are_dropped(self):
        """A model that ignores its vocabulary must not smuggle in another layer."""
        client = make_client(
            {"nodes": [], "edges": [{"source_name": "A", "target_name": "B",
                                     "rel_type": "SEEKS"}]}
        )
        _, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SPATIAL
        )

        assert edges == []

    @pytest.mark.asyncio
    async def test_malformed_json_yields_nothing_and_does_not_raise(self):
        message = MagicMock()
        message.content = "not json at all"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)

        nodes, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_api_failure_yields_nothing_and_does_not_raise(self):
        """One bad unit must not abort a chapter."""
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

        nodes, edges = await CandidateExtractor(client=client).extract_unit(
            unit(), Layer.SOCIAL
        )

        assert nodes == []
        assert edges == []


class TestExtractUnits:
    @pytest.mark.asyncio
    async def test_runs_every_layer_over_every_unit(self):
        client = make_client({"nodes": [], "edges": []})
        await CandidateExtractor(client=client).extract_units([unit(), unit()])

        assert client.chat.completions.create.await_count == 6  # 2 units x 3 layers
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_canon/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.canon.extract'`

- [ ] **Step 3: Implement**

Create `backend/canon/extract.py`:

```python
"""Extract candidate entities and relationships, one layer at a time.

Three focused passes per unit beat one general pass: a prompt that knows only
about containment produces cleaner spatial output than one asked to find
everything at once, and when a layer extracts badly it is diagnosable on its own.

Candidates are keyed by NAME. Minting deterministic ids and collapsing an entity
across chapters is stage 2b's job; doing it here would entangle the tuning loop
with dedup logic it would have to be correct about first.
"""

import asyncio
import json
import logging

from openai import AsyncOpenAI

from backend.canon.models import CandidateEdge, CandidateNode, ExtractionUnit
from backend.core.config import settings
from backend.graph.schema import LAYER_MAP, EntityType, Layer

logger = logging.getLogger(__name__)

EXTRACTION_MODEL = "gpt-4o-mini"

_LAYER_GUIDANCE = {
    Layer.SPATIAL: (
        "Physical arrangement only: what contains what, what connects to what, "
        "and where a character or object is located."
    ),
    Layer.SOCIAL: (
        "Relationships between people and factions: who knows, serves, guards, "
        "owns, allies with, or is hostile to whom."
    ),
    Layer.NARRATIVE: (
        "Plot machinery: what an agent WANTS (SEEKS, with the reason in "
        "`evidence`), what it works against (OPPOSES), hidden identities "
        "(IDENTITY_OF), quest structure, and standing threats."
    ),
}


def layer_vocabulary(layer: Layer) -> list[str]:
    """The relationship types belonging to a layer, from LAYER_MAP.

    Derived rather than listed, so adding a relationship type cannot leave the
    extractor silently unaware of it.
    """
    return sorted(r.value for r, mapped in LAYER_MAP.items() if mapped is layer)


def _prompt(unit: ExtractionUnit, layer: Layer) -> str:
    vocab = layer_vocabulary(layer)
    entity_types = sorted(t.value for t in EntityType)
    return f"""\
Extract {layer.value}-layer canon from this passage of a D&D sourcebook.

{_LAYER_GUIDANCE[layer]}

Use ONLY these relationship types: {", ".join(vocab)}
Use ONLY these entity types: {", ".join(entity_types)}

Rules:
- Extract only what the passage states. Do not infer from outside knowledge.
- Name entities as the passage names them. Do not invent ids.
- An entity worth extracting is one another passage could refer to. Skip scenery.
- If the passage states nothing for this layer, return empty lists. That is a
  valid and common answer.

Return JSON:
{{"nodes": [{{"name": ..., "entity_type": ..., "description": ...}}],
  "edges": [{{"source_name": ..., "target_name": ..., "rel_type": ..., "evidence": ...}}]}}

Chapter: {unit.chapter_title}
Section(s): {", ".join(unit.headings)}

---
{unit.markdown}
"""


class CandidateExtractor:
    """Runs the per-layer passes. Never raises: a bad unit yields nothing."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        concurrency: int = 6,
    ):
        self.client = client or AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = model or EXTRACTION_MODEL
        self._semaphore = asyncio.Semaphore(concurrency)

    async def extract_unit(
        self,
        unit: ExtractionUnit,
        layer: Layer,
    ) -> tuple[list[CandidateNode], list[CandidateEdge]]:
        try:
            async with self._semaphore:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": _prompt(unit, layer)}],
                    response_format={"type": "json_object"},
                )
            payload = json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:  # noqa: BLE001 - one unit must not abort a chapter
            logger.warning(
                "extraction failed for %s / %s: %s", unit.chapter_slug, layer.value, exc
            )
            return [], []

        return self._parse(payload, unit, layer)

    async def extract_units(
        self,
        units: list[ExtractionUnit],
        layers: list[Layer] | None = None,
    ) -> tuple[list[CandidateNode], list[CandidateEdge]]:
        wanted = layers or list(Layer)
        results = await asyncio.gather(
            *(self.extract_unit(u, layer) for u in units for layer in wanted),
            return_exceptions=True,
        )

        nodes: list[CandidateNode] = []
        edges: list[CandidateEdge] = []
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("extraction task failed: %s", result)
                continue
            unit_nodes, unit_edges = result
            nodes.extend(unit_nodes)
            edges.extend(unit_edges)
        return nodes, edges

    @staticmethod
    def _parse(
        payload: dict,
        unit: ExtractionUnit,
        layer: Layer,
    ) -> tuple[list[CandidateNode], list[CandidateEdge]]:
        allowed = set(layer_vocabulary(layer))
        heading = unit.headings[0] if unit.headings else ""

        nodes = [
            CandidateNode(
                name=str(n.get("name", "")).strip(),
                entity_type=str(n.get("entity_type", "")).strip(),
                description=str(n.get("description", "") or ""),
                layer=layer.value,
                chapter_slug=unit.chapter_slug,
                section_heading=heading,
            )
            for n in payload.get("nodes", [])
            if str(n.get("name", "")).strip()
        ]

        edges = [
            CandidateEdge(
                source_name=str(e.get("source_name", "")).strip(),
                target_name=str(e.get("target_name", "")).strip(),
                rel_type=str(e.get("rel_type", "")).strip(),
                evidence=str(e.get("evidence", "") or ""),
                layer=layer.value,
                chapter_slug=unit.chapter_slug,
                section_heading=heading,
            )
            for e in payload.get("edges", [])
            # A model that ignores its vocabulary must not smuggle another layer in.
            if str(e.get("rel_type", "")).strip() in allowed
            and str(e.get("source_name", "")).strip()
            and str(e.get("target_name", "")).strip()
        ]

        return nodes, edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_extract.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add backend/canon/extract.py tests/test_canon/test_extract.py
git commit -m "feat(canon): add per-layer candidate extraction"
```

---

### Task 4: CLI and the chapter 3 tuning run

**Files:**
- Create: `backend/scripts/extract_canon.py`
- Create: `tests/test_canon/test_extract_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3, plus `assemble_chapters`, `PageExtractor`, `TranscriptCache`, `extractable_subset`
- Produces: `load_chapters() -> list[Chapter]`, `find_chapter(chapters, needle) -> Chapter`, `async run(chapter_title, grade_against, layers, out_path) -> dict`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canon/test_extract_cli.py`:

```python
"""CLI plumbing. The extraction itself is tested in test_extract.py."""

import pytest

from backend.canon.models import Chapter
from backend.scripts.extract_canon import find_chapter


def chapter(title: str) -> Chapter:
    return Chapter(slug="s", title=title, start_page=1, end_page=2, markdown="x")


class TestFindChapter:
    def test_matches_on_a_prefix(self):
        chapters = [chapter("Chapter 3: The Village of Barovia"),
                    chapter("Chapter 4: Castle Ravenloft")]

        assert find_chapter(chapters, "Chapter 3").title.startswith("Chapter 3")

    def test_match_is_case_insensitive(self):
        chapters = [chapter("Chapter 3: The Village of Barovia")]

        assert find_chapter(chapters, "chapter 3") is chapters[0]

    def test_unknown_chapter_raises_with_the_available_titles(self):
        chapters = [chapter("Chapter 3: The Village of Barovia")]

        with pytest.raises(ValueError) as exc:
            find_chapter(chapters, "Chapter 9")
        assert "Chapter 3" in str(exc.value)

    def test_ambiguous_prefix_raises(self):
        chapters = [chapter("Chapter 1: Into the Mists"),
                    chapter("Chapter 10: The Ruins of Berez")]

        with pytest.raises(ValueError):
            find_chapter(chapters, "Chapter 1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_canon/test_extract_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.scripts.extract_canon'`

- [ ] **Step 3: Implement**

Create `backend/scripts/extract_canon.py`:

```python
#!/usr/bin/env python3
"""Extract canon candidates from a chapter and score them against the golden set.

Nothing here writes to Neo4j. The output is a candidate set on disk plus a
score, which keeps a tuning run from being able to corrupt anything.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.assembler import assemble_chapters
from backend.canon.cache import TranscriptCache
from backend.canon.extract import CandidateExtractor
from backend.canon.grade import grade
from backend.canon.models import Chapter
from backend.canon.page_extractor import PageExtractor
from backend.canon.sections import pack_sections, split_sections
from backend.canon.seed_loader import SEED_DIR, extractable_subset
from backend.core.config import settings
from backend.graph.schema import Layer

DEFAULT_PDF = Path("data/cos.pdf")


def load_chapters(pdf_path: Path = DEFAULT_PDF, book_slug: str = "cos") -> list[Chapter]:
    """Rebuild chapters from the transcript cache. No API calls: cache only."""
    cache = TranscriptCache(settings.canon_dir / book_slug)
    extractor = PageExtractor(pdf_path)
    try:
        transcripts = [
            t
            for page in extractor.extract()
            if (t := cache.get(page.page_number, page.sha256)) is not None
        ]
    finally:
        extractor.close()
    return assemble_chapters(transcripts)


def find_chapter(chapters: list[Chapter], needle: str) -> Chapter:
    """Find one chapter by case-insensitive title prefix."""
    hits = [c for c in chapters if c.title.lower().startswith(needle.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(
            f"no chapter matching {needle!r}. Available: "
            + ", ".join(c.title for c in chapters)
        )
    raise ValueError(
        f"{needle!r} is ambiguous: " + ", ".join(c.title for c in hits)
    )


async def run(
    chapter_title: str,
    grade_against: str | None,
    layers: list[Layer] | None,
    out_path: Path | None,
) -> dict:
    chapter = find_chapter(load_chapters(), chapter_title)
    units = pack_sections(split_sections(chapter))
    print(f"{chapter.title}: {len(units)} units")

    nodes, edges = await CandidateExtractor().extract_units(units, layers=layers)
    print(f"  {len(nodes)} candidate nodes, {len(edges)} candidate edges")

    if out_path:
        out_path.write_text(
            json.dumps(
                {"nodes": [asdict(n) for n in nodes], "edges": [asdict(e) for e in edges]},
                indent=2,
            )
        )
        print(f"  wrote {out_path}")

    summary: dict = {"nodes": len(nodes), "edges": len(edges)}

    if grade_against:
        data = yaml.safe_load((SEED_DIR / "village-of-barovia.yaml").read_text())
        report = grade(nodes, edges, extractable_subset(data, grade_against))
        print(f"\n  node recall: {report.node_recall:.2f}")
        print(f"  edge recall: {report.edge_recall:.2f}")
        if report.missing_nodes:
            print(f"  MISSING nodes ({len(report.missing_nodes)}): "
                  f"{', '.join(report.missing_nodes)}")
        if report.missing_edges:
            print(f"  MISSING edges ({len(report.missing_edges)}):")
            for m in report.missing_edges:
                print(f"    {m}")
        print(f"\n  unmatched candidates ({len(report.unmatched_nodes)}) "
              "-- NOT scored, spot-check for fabrication:")
        for name in report.unmatched_nodes:
            print(f"    {name}")
        summary["node_recall"] = report.node_recall
        summary["edge_recall"] = report.edge_recall

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapter", help="Chapter title prefix, e.g. 'Chapter 3'")
    parser.add_argument("--grade", dest="grade_against", metavar="SOURCE",
                        help="Grade against the seed subset for this source, e.g. ch3")
    parser.add_argument("--layer", action="append", dest="layers",
                        choices=[layer.value for layer in Layer],
                        help="Restrict to one layer; repeatable")
    parser.add_argument("-o", "--out", type=Path, help="Write candidates as JSON")
    args = parser.parse_args()

    layers = [Layer(v) for v in args.layers] if args.layers else None
    asyncio.run(run(args.chapter, args.grade_against, layers, args.out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_canon/test_extract_cli.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: green. Report the count.

- [ ] **Step 6: The chapter 3 tuning run**

This is the point of the plan. It makes real API calls — roughly 15k input tokens with
`gpt-4o-mini`, well under a cent.

```bash
SP=/private/tmp/claude-501/-Users-csinger-projects-agentic-dm/52a0dd1b-7233-44b1-b4e8-ed61a72765e5/scratchpad
uv run python -m backend.scripts.extract_canon "Chapter 3" --grade ch3 -o "$SP/ch3-candidates.json"
```

Record in your report, verbatim: the unit count, node and edge counts, both recall figures,
the full missing list, and the full unmatched list.

**The bar is node recall ≥ 0.9.** If it comes in lower, that is the expected first result,
not a failure — report the misses and stop. **Do not tune the prompt yourself.** The whole
point of building the harness first is that prompt changes get made against evidence, and
the controller decides which evidence matters.

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/extract_canon.py tests/test_canon/test_extract_cli.py
git commit -m "feat(canon): add extraction CLI with golden-set grading"
```

---

### Task 5: Subset matching, so recall measures extraction rather than naming

**Why this exists.** Task 4's chapter-3 run scored node recall 0.67 and edge recall 0.12,
and the miss lists show the cause is the matcher, not the extractor. From the unmatched
candidates:

| Golden expects | Extractor produced | Matched |
|---|---|---|
| `Strahd von Zarovich` | `Strahd` (×6) | no |
| `Church of Barovia` | `Church`, `The Church` | no |
| `Village of Barovia` | `Barovia` (×6) | no |
| `Ismark Kolyanovich` | `Ismark` (×3) | no |

`normalize_name` folds case, punctuation, articles and whitespace, then compares for
**exact equality**, so a shorter form never matches a longer one. The spec set out to avoid
"recall as a measure of naming luck rather than extraction quality"; the matcher as built
is that failure. Edge recall is worse because an edge needs both endpoints to match, so
endpoint failures compound multiplicatively.

**Not in scope here:** two misses are genuine corpus defects — the transcription reads
`Blood of the Vine Tavern` where the book says "on", and `Morgatha` where it says
"Morgantha". Those are vision-transcription errors in proper nouns, recorded for stage 2b's
resolution work. Do not paper over them by making the matcher fuzzy enough to absorb typos;
that would hide real extraction errors too.

**Files:**
- Modify: `backend/canon/grade.py`
- Modify: `tests/test_canon/test_grade.py`

**Interfaces:**
- Consumes: `CandidateNode`, `CandidateEdge`, `GradeReport` (unchanged)
- Produces: `names_match(candidate: str, golden: str) -> bool`. `normalize_name` and `grade` keep their signatures.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_canon/test_grade.py`:

```python
class TestSubsetMatching:
    """A shorter name the passage actually used must match the key's fuller form.

    The extractor writes what the book writes. Chapter 3 says "Strahd" far more
    often than "Strahd von Zarovich", and grading the former as a miss measures
    naming convention rather than whether the entity was found.
    """

    def test_shorter_candidate_matches_longer_golden(self):
        assert names_match("Strahd", "Strahd von Zarovich")
        assert names_match("Church", "Church of Barovia")
        assert names_match("Barovia", "Village of Barovia")
        assert names_match("Ismark", "Ismark Kolyanovich")

    def test_longer_candidate_matches_shorter_golden(self):
        """Direction must not matter -- the extractor may be more specific."""
        assert names_match("Ireena Kolyana", "Ireena")

    def test_articles_are_still_folded(self):
        assert names_match("The Church", "Church of Barovia")

    def test_unrelated_names_do_not_match(self):
        assert not names_match("Ismark", "Ireena")
        assert not names_match("Bildrath", "Parriwimple")

    def test_a_shared_generic_token_is_not_enough(self):
        """"Village of Barovia" and "Village of Krezk" share a token and are
        different places. Subset matching must not collapse them."""
        assert not names_match("Village of Krezk", "Village of Barovia")

    def test_typos_do_not_match(self):
        """Deliberate: a transcription typo is a real defect, not naming variance.

        Making the matcher fuzzy enough to absorb "Morgatha" -> "Morgantha" would
        also hide genuine extraction errors.
        """
        assert not names_match("Morgatha", "Morgantha")
        assert not names_match("Blood of the Vine Tavern", "Blood on the Vine Tavern")


class TestSubsetMatchingInGrade:
    def test_recall_counts_a_shorter_candidate(self):
        g = golden(nodes=[gnode("Strahd von Zarovich")])
        report = grade([cnode("Strahd")], [], g)

        assert report.node_recall == 1.0
        assert report.unmatched_nodes == []

    def test_edge_endpoints_use_subset_matching_too(self):
        g = golden(
            nodes=[gnode("Strahd von Zarovich"), gnode("Ireena Kolyana")],
            edges=[gedge("cos:npc:strahd von zarovich", "cos:npc:ireena kolyana", "SEEKS")],
        )
        report = grade([], [cedge("Strahd", "Ireena", "SEEKS")], g)

        assert report.edge_recall == 1.0

    def test_an_ambiguous_candidate_is_reported_as_a_collision(self):
        """If a short name matches two golden entries, that is ambiguity, and the
        harness must say so rather than silently crediting one."""
        g = golden(nodes=[gnode("Strahd von Zarovich"), gnode("Strahd Zombie")])
        report = grade([cnode("Strahd")], [], g)

        assert report.collisions, "an ambiguous candidate must be surfaced"
```

Add `names_match` to the existing import from `backend.canon.grade`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_canon/test_grade.py::TestSubsetMatching -v`
Expected: FAIL with `ImportError: cannot import name 'names_match'`. Capture the output.

- [ ] **Step 3: Implement subset matching**

In `backend/canon/grade.py`, add below `normalize_name`:

```python
def names_match(candidate: str, golden: str) -> bool:
    """True when a candidate name refers to the same entity as a golden name.

    Exact folded equality is too strict: the extractor writes what the passage
    writes, and chapter 3 says "Strahd" far more often than "Strahd von
    Zarovich". Grading the former as a miss measures naming convention rather
    than whether the entity was found.

    So one name also matches the other when its tokens are a subset -- "strahd"
    within "strahd von zarovich", "church" within "church of barovia". Subset,
    not substring: "Village of Krezk" and "Village of Barovia" share a token but
    neither contains the other, so they correctly do not match.

    Deliberately NOT fuzzy. A typo like "Morgatha" for "Morgantha" is a real
    defect -- a transcription error or an extraction error -- and absorbing it
    here would hide the class of problem this harness exists to surface.
    """
    a, b = normalize_name(candidate), normalize_name(golden)
    if a == b:
        return True
    if not a or not b:
        return False

    a_tokens, b_tokens = set(a.split()), set(b.split())
    return a_tokens < b_tokens or b_tokens < a_tokens
```

Then replace exact-equality comparisons in `grade` with `names_match`:

- Node matching: instead of intersecting `candidate_names` with the golden's acceptable
  set, a golden entry is hit when **any** candidate matches **any** of its acceptable
  names. Track which candidates were consumed so `unmatched_nodes` stays correct.
- Edge matching: resolve each golden endpoint id to its acceptable names as now, but
  compare endpoints with `names_match` rather than set membership.
- **Ambiguity goes to `collisions`.** If one candidate name matches more than one golden
  node id, append a line naming the candidate and the ids it matched. This reuses the
  diagnostic added in the previous fix round and is why that field exists.

Keep `_find_collisions`'s existing golden-vs-golden detection; ambiguous candidates are an
additional source of collision entries, not a replacement.

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/test_canon/test_grade.py -v`
Expected: all pass, including the pre-existing tests. If a pre-existing test now fails,
**report it rather than editing it** — subset matching is a behaviour change and an
existing assertion contradicting it is information, not an obstacle.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: green. Report the count.

- [ ] **Step 6: Re-run chapter 3 and report the new numbers**

```bash
SP=/private/tmp/claude-501/-Users-csinger-projects-agentic-dm/52a0dd1b-7233-44b1-b4e8-ed61a72765e5/scratchpad
uv run python -m backend.scripts.extract_canon "Chapter 3" --grade ch3 -o "$SP/ch3-candidates-v2.json"
```

Report both recall figures, the full miss list, and any collisions, verbatim. **Do not tune
the extraction prompt** — that decision remains the controller's, and this run exists to
separate matcher error from extractor error, not to chase a number.

- [ ] **Step 7: Commit**

```bash
git add backend/canon/grade.py tests/test_canon/test_grade.py
git commit -m "fix(canon): match names by token subset so recall measures extraction"
```

---

## Verification

Whole suite: `uv run pytest -q` — 316 existing plus ~42 new.
Without a database: `uv run pytest -q -m "not neo4j"` must pass.
Lint: `uv run ruff check backend/canon/ backend/scripts/extract_canon.py tests/test_canon/`

## Notes for the Implementer

- **Nothing writes to Neo4j.** If a task seems to need the graph, it belongs to 2b or 2c.
- **Recall is the only number.** Precision is not computed, on purpose — the golden set is not exhaustive, so unmatched candidates are listed for a human rather than scored. Do not add a precision metric.
- **Do not tune prompts.** Task 4 Step 6 produces evidence; acting on it is a separate decision.
- Layer vocabularies come from `LAYER_MAP`. Never write a relationship type as a literal in a prompt.
