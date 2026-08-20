# Agent Lab

The lab interface: grounded answers from the Curse of Strahd canon graph, with
their provenance kept visible.

```bash
uv run uvicorn backend.api.main:app --reload   # the API, on :8000
cd web && npm run dev                          # this, on :3000
```

`NEXT_PUBLIC_API_BASE` overrides where it looks for the API; it defaults to
`http://127.0.0.1:8000/api`.

## What this replaced, and what had to survive

It replaces `frontend/lab.html`, a second Vite entry bolted onto the campaign
UI and sharing no component with it. The port changed no API contract.

What a rewrite most easily loses is the part that took the longest to build:
the labels that say how much to trust each thing on screen. They are all here,
and each is a claim somebody measured rather than decoration.

- **Per PASSAGE, not per answer** — `by name` against `keyword match`. A result
  that resolved a name still carries text passages, and labelling the whole
  answer by how the question resolved credited the graph for answers a keyword
  match earned. That bug was fixed in three separate places.
- **`carried from the conversation`** — this question resolved no name of its
  own and was anchored on what came before.
- **`derived · guessed`** — derived edges come from the book's structure;
  guessed ones come from an extractor and roughly a third are wrong.
- **`(withheld)`** — proposed edges existed and were held back. Withheld is not
  the same as absent.
- **`rate unverified`** — every price in `backend/core/pricing.yaml` is a claim
  about the outside world this repository cannot check, and a total built from
  unchecked rates says so.
- **Provenance colour in the working set** — green for a name a question
  resolved, amber for one an answer used, blue for one a tool fetched. Grey is
  a fourth state: a name the agent knows only through a relationship line, not
  an entity it holds. "It never knew" looks grey; "it forgot" looks like a name
  that used to have a colour and is gone.

## The working set is a ledger, not a picture

It was a force graph, twice patched and still wrong, because the data is not a
network. A typical turn holds ~9 entities with ~3 edges between them — the
simulation scattered the disconnected majority and autofit zoomed until nodes
were sub-pixel. Worse, most held edges point at a name that is NOT a held node
(76 edges against 3 nodes on a real turn), and a node-and-edge drawing can
only show the node-to-node minority; it drew 4 of those 76 and counted the
rest "not drawn", which is to say it hid most of the memory.

The panel now mirrors `Subgraph.render()` — the exact text the model reads —
one entity per block, most recently touched first (which is reverse eviction
order), relationships grouped by type and direction, derived bright and
guessed dim. What the developer sees is what the model was shown, not a
projection of it.

Terse labels with the full reason one hover away. Terse is only honest when the
long version is reachable.

## Layout

A drag handle, not a toggle. Two hardcoded widths were two guesses at what
somebody wanted to read, and both were wrong.
