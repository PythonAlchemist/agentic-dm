"""Content-hash-validated cache for page transcriptions."""

import json
from pathlib import Path

from backend.canon.models import PageTranscript


class TranscriptCache:
    """Store page transcripts on disk, keyed by page and validated by image hash.

    Files are written per page rather than per hash so the output stays
    human-browsable. The sidecar records the source image hash; a mismatch is
    treated as a miss, so changing the source PDF re-transcribes automatically.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.pages_dir = self.root / "pages"

    def page_path(self, page_number: int) -> Path:
        return self.pages_dir / f"{page_number:04d}.md"

    def _meta_path(self, page_number: int) -> Path:
        return self.pages_dir / f"{page_number:04d}.json"

    def get(self, page_number: int, sha256: str) -> PageTranscript | None:
        """Return the cached transcript, or None on miss or hash mismatch."""
        md_path = self.page_path(page_number)
        meta_path = self._meta_path(page_number)
        if not md_path.exists() or not meta_path.exists():
            return None

        meta = json.loads(meta_path.read_text())
        if meta.get("image_sha256") != sha256:
            return None

        return PageTranscript(
            page_number=page_number,
            markdown=md_path.read_text(),
            image_sha256=sha256,
            model=meta.get("model", ""),
            status="ok",
            input_tokens=meta.get("input_tokens", 0),
            output_tokens=meta.get("output_tokens", 0),
        )

    def put(self, transcript: PageTranscript) -> None:
        """Persist a successful transcript. Failures are intentionally not cached."""
        if transcript.status != "ok":
            return

        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.page_path(transcript.page_number).write_text(transcript.markdown)
        self._meta_path(transcript.page_number).write_text(
            json.dumps(
                {
                    "image_sha256": transcript.image_sha256,
                    "model": transcript.model,
                    "input_tokens": transcript.input_tokens,
                    "output_tokens": transcript.output_tokens,
                },
                indent=2,
            )
        )
