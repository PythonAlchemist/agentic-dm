"""Dataclasses passed between canon pipeline stages."""

from dataclasses import dataclass


@dataclass
class PageImage:
    """One rendered or extracted page image from a source PDF."""

    page_number: int  # 1-indexed
    image_bytes: bytes
    ext: str  # "png", "jpeg", or "jpg" -- the only formats the vision API accepts
    width: int
    height: int
    sha256: str


@dataclass
class PageTranscript:
    """Markdown transcription of a single page."""

    page_number: int
    markdown: str
    image_sha256: str
    model: str
    status: str = "ok"  # "ok" | "failed"
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Chapter:
    """A run of consecutive pages under one chapter heading."""

    slug: str
    title: str
    start_page: int
    end_page: int
    markdown: str


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
    """One section, sized to fit a single extraction pass."""

    chapter_slug: str
    chapter_title: str
    heading: str
    section_index: int
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
    # `(chapter_slug, section_heading)` is not a unique key -- duplicate H2
    # headings occur within a chapter (four "Treasure" sections in Chapter 4,
    # three "Actions" sections in Appendix D). `section_index` is.
    section_index: int = -1


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
    section_index: int = -1


@dataclass
class GradeReport:
    """Recall against a golden subset, plus what to look at by hand.

    Precision is deliberately absent: the golden set is not exhaustive, so an
    unmatched candidate is usually a legitimate entity the key omits rather than
    a fabrication. Scoring it would punish thoroughness.

    `node_ceiling` / `edge_ceiling` are the best unambiguous recall this golden
    subset admits at all -- the key graded against itself. Below 1.0 means the
    key contains entries indistinguishable under the matcher, and no extractor
    can reach the difference. Reported next to the score so a bar can never
    again be set above what is achievable without anyone noticing.
    """

    node_recall: float
    edge_recall: float
    node_recall_unambiguous: float
    edge_recall_unambiguous: float
    node_ceiling: float
    edge_ceiling: float
    missing_nodes: list[str]
    missing_edges: list[str]
    unmatched_nodes: list[str]
    unmatched_edges: list[str]
    collisions: list[str]
    edge_collisions: list[str]
