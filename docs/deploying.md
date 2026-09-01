# Deploying the lab

Vercel for the web app, Railway for the API and a Neo4j container, gated so
only people you have confirmed own the books can read it.

```
Vercel (Next.js)  --bearer token-->  Railway (FastAPI)  --bolt-->  Neo4j
   the login wall                      checks the token          the graph
```

## The one thing not to get wrong

**The gate is on the API, not the web app.** A login wall in front of Vercel
alone leaves the Railway URL reachable, and whoever finds it gets a searchable
copy of *Curse of Strahd* and *Keys from the Golden Vault* -- 1,378 sections,
1.6 million characters -- without ever loading the page. `backend/api/auth.py`
holds the rule and `tests/test_api/test_auth.py` asserts it over all 97 `/api`
routes, so a router added later is covered the day it is added.

The corollary: **`ACCESS_TOKENS` unset means the API is open.** That default is
what keeps local development and the test suite working, and it is the one
setting worth checking twice. The API prints which it is on every boot:

```
[auth] gated -- 3 reader(s): chris, sam, jo
[auth] OPEN -- no ACCESS_TOKENS set; every endpoint answers anyone
```

## 1. Neo4j

Add a Neo4j service on Railway from the `neo4j:5` image, with a volume mounted
at `/data` and `NEO4J_AUTH=neo4j/<a long password>`.

**Railway rather than Aura Free**, which fits (the free tier allows 200k nodes
and 400k relationships; this graph is 13,391 and 40,929) but pauses after three
days idle and is deleted after thirty. A table that plays weekly would meet a
paused database most weeks.

## 2. The API

Railway builds the `Dockerfile` at the repo root and health-checks `/health`.
Set:

| Variable | Value |
|---|---|
| `NEO4J_URI` | `bolt://<neo4j service>.railway.internal:7687` |
| `NEO4J_USER` | `neo4j` |
| `NEO4J_PASSWORD` | what you set above |
| `OPENAI_API_KEY` | your key |
| `OPENAI_MODEL` | e.g. `gpt-4o-mini` |
| `DEEPGRAM_API_KEY` | only if you use audio |
| `ACCESS_TOKENS` | see below -- **without it the API is open** |
| `ALLOWED_ORIGINS` | your Vercel URL, once you have it |

## 3. Fill the graph

The image ships no book text -- `.dockerignore` keeps `data/` and `sessions/`
out of every layer, because an image is a thing that gets pushed to a registry.
The graph is copied over bolt from your machine instead:

```bash
uv run python -m backend.scripts.push_graph --to bolt+s://<host>:7687 --to-password '<pw>'
# reads the target, prints what it would write, writes nothing
uv run python -m backend.scripts.push_graph --to bolt+s://<host>:7687 --to-password '<pw>' --apply
```

Dry run unless `--apply`, and it refuses a target that already holds nodes
unless you also pass `--wipe`. Locally this copies 13,391 nodes and 40,929
relationships in about nine seconds. Afterwards:

```bash
NEO4J_URI=bolt+s://<host>:7687 NEO4J_PASSWORD='<pw>' \
  uv run python -m backend.scripts.check_invariants
```

All seven must hold. If one is red the copy is wrong; stop and read
`backend/campaign/invariants.py`, which says what each one means.

`a canon entity says whether the book names it` is the one to expect on a
fresh copy: 154 entities cite no prose, and they are legitimate -- the DM
ruled them worth keeping -- but each has to say so on itself before the check
passes. `uv run python -m backend.scripts.mark_unnamed --apply` writes that,
and `lookup` then returns `named_by_book` so a reader can see it.

## 4. Issue tokens

One per person, so a token can be revoked without disturbing anyone else and a
leaked one says whose it was.

```bash
uv run python -m backend.scripts.mint_token sam
```

It prints the token once -- give that to Sam -- and the full `ACCESS_TOKENS`
line to paste into Railway, with everyone who already had one. Only the SHA-256
is stored, so the environment is not a set of working credentials and a lost
token means minting another, not looking the old one up.

**To revoke:** delete that person's entry from `ACCESS_TOKENS` and redeploy.

## 5. The web app

Vercel, root directory `web`. One variable:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE` | `https://<railway app>.up.railway.app/api` |

Then put that Vercel URL into the API's `ALLOWED_ORIGINS` and redeploy it.

**The root directory is load-bearing and easy to get wrong.** `vercel --prod`
run from `web/` uploads that folder as the deployment root, so it works even
when the project's Root Directory is `.` -- and a git-triggered build does not,
because Vercel clones the whole repo and there is no `package.json` at the top.
The two paths disagree silently: CLI deploys succeed, pushes build nothing.

That is what happened here. The API auto-deploys from GitHub and the web app
did not, so a push updated one half of the app and left the other on a build
from the previous day, with no failure anywhere to notice. If the UI is not
showing a change you know you pushed, check this first.

Root Directory is `web` and the repo IS connected, so pushes build the web app
the way they already redeploy the API. To reconnect it, note that neither
directory has both halves -- `.vercel` lives in `web/`, `.git` at the repo root
-- so the URL has to be given explicitly:

```bash
vercel git connect https://github.com/PythonAlchemist/agentic-dm.git
```

After that, deploy from the REPO ROOT rather than `web/` if you deploy by hand
at all -- Root Directory is applied to CLI uploads too, so `vercel --prod` from
inside `web/` would then look for `web/web`.

## Checking it worked

```bash
curl -i https://<api>/health                       # 200, no token
curl -i https://<api>/api/lab/config               # 401
curl -i -H "Authorization: Bearer <token>" https://<api>/api/lab/config   # 200
```

If the middle one returns 200, `ACCESS_TOKENS` did not take and the books are
public. That is the check worth running after every deploy.

## This deployment, by name

Written down because it existed only in two dashboards, and a thing that exists
only in a dashboard cannot be rebuilt from a clone. **No secrets are here** --
every value below is an identifier or a public URL. `GRAPH_PASSWORD`,
`ACCESS_TOKENS` and `OPENAI_API_KEY` live only in Railway's variables and are
read with `railway variables --json` piped straight into the environment, never
echoed. (`railway add --variables` DOES echo its inputs, which leaked a
password once and forced a rotation.)

| | |
|---|---|
| Railway project | `agentic-dm` · `d2760a32-f2f0-4cb4-aa95-8729bf969216` |
| service `api` | `532bdedd-d49a-41ec-96f8-564d132cee23`, from the GitHub repo, auto-redeploys on push |
| service `neo4j` | `cb7a74f6-f630-4d05-bd40-6869a8bbf270`, 5GB volume at `/data`, private network only |
| Vercel project | `agentic-dm` · `prj_bjo8UG250d5gsa434zyOcTqoZPFq` |
| Vercel org | `team_VdggpVvkEtJ7hAnbaFETBX2S` |
| App | https://agentic-dm.vercel.app |
| API | https://api-production-bb1e4.up.railway.app |

Variables on `api`, names only: `ACCESS_TOKENS`, `ALLOWED_ORIGINS`,
`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `OPENAI_API_KEY`, `OPENAI_MODEL`,
`PORT`. On `neo4j`: `GRAPH_PASSWORD`, `NEO4J_AUTH`, and the `NEO4J_server_*`
tuning. **Nothing on `neo4j` may be named `NEO4J_PASSWORD`** -- that image
reads every `NEO4J_*` variable as a config setting and crash-loops on one it
does not recognise, which is why the password is `GRAPH_PASSWORD` and the api
refers to it as `${{neo4j.GRAPH_PASSWORD}}`.

The `neo4j` service keeps a TCP proxy open deliberately. It is how the graph is
refreshed -- `push_graph`, `mark_unnamed`, `check_invariants` and `audit_scope`
all reach the deployed database through it -- and closing it between syncs
would mean recreating it by hand every time.

## What is deliberately not deployed

- **The websocket** at `/api/chat/ws/{session_id}` is gated like everything
  else and accepts a valid token, but a browser cannot set a header on a
  handshake, so it is unreachable from the web app while gated. Nothing in
  `web/` opens it. Wiring it up needs a real handshake -- not the token in a
  query string, which would put a credential in every proxy log.
- **`data/` and `sessions/`** never leave your machine. The graph carries the
  prose it needs; the PDFs, the gazetteer and the harvested pages stay put.
