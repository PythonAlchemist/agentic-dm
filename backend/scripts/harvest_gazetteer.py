#!/usr/bin/env python3
"""Harvest the Forgotten Realms Wiki's Curse of Strahd index into a local gazetteer.

This is the only part of the gazetteer that touches the network. It fetches, hands the
payloads to `backend.canon.wiki` to parse, and writes JSON. No LLM calls, no Neo4j, no
extraction code touched -- wiring the result into the pipeline is a separate decision.

The output lands under `data/`, which is gitignored, because the wiki's text is
third-party CC-BY-SA content: ours to use, not ours to commit and redistribute.

    uv run python -m backend.scripts.harvest_gazetteer --out data/gazetteer/curse-of-strahd.json
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.canon.wiki import API_URL, INDEX_PAGE, WikiPage, build_document, parse_index
from backend.canon.wiki import parse_pages_response as parse_pages

DEFAULT_OUT = Path("data/gazetteer/curse-of-strahd.json")

#: MediaWiki accepts 50 titles per query, so 677 entities cost ~14 calls, not 677.
BATCH_SIZE = 50
#: Courtesy pause between calls. We are a guest on someone else's server.
DELAY_SECONDS = 0.5
USER_AGENT = "agentic-dm canon gazetteer harvester (https://github.com/PythonAlchemist)"


def fetch(params: dict[str, str], api_url: str = API_URL, timeout: int = 30) -> dict:
    """GET one MediaWiki API call and return the decoded JSON."""
    url = f"{api_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def fetch_index_wikitext(api_url: str = API_URL, page: str = INDEX_PAGE) -> str:
    payload = fetch(
        {
            "action": "parse",
            "page": page.replace(" ", "_"),
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
        },
        api_url,
    )
    return payload["parse"]["wikitext"]


def fetch_pages(titles: list[str], api_url: str = API_URL) -> dict[str, WikiPage]:
    """Fetch every title in batches, keyed by the title as it was asked for."""
    pages: dict[str, WikiPage] = {}
    for start in range(0, len(titles), BATCH_SIZE):
        batch = titles[start : start + BATCH_SIZE]
        payload = fetch(
            {
                "action": "query",
                "prop": "revisions",
                "rvslots": "main",
                "rvprop": "content",
                "titles": "|".join(batch),
                "format": "json",
                "formatversion": "2",
            },
            api_url,
        )
        pages.update(parse_pages(payload))
        print(f"  fetched {min(start + BATCH_SIZE, len(titles))}/{len(titles)}", flush=True)
        if start + BATCH_SIZE < len(titles):
            time.sleep(DELAY_SECONDS)
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument(
        "--fetch-date",
        default=date.today().isoformat(),
        help="Recorded in the document's source block. Defaults to today.",
    )
    args = parser.parse_args()

    print(f"Reading the {INDEX_PAGE} index from {args.api_url}")
    index_entries = parse_index(fetch_index_wikitext(args.api_url))
    print(f"  {len(index_entries)} indexed entities")

    targets = list(dict.fromkeys(entry.target for entry in index_entries))
    print(f"Fetching {len(targets)} pages in batches of {BATCH_SIZE}")
    pages = fetch_pages(targets, args.api_url)

    document = build_document(index_entries, pages, fetch_date=args.fetch_date)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")

    counts = document["counts"]
    print(f"Wrote {args.out}")
    print(f"  entries       {counts['entries']}")
    print(f"  with a page   {counts['page_exists']}")
    print(f"  redlinks      {counts['redlinks']}")
    print(f"  redirects     {counts['redirects']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
