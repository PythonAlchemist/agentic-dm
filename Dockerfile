# The API, for Railway.
#
# WHAT IS NOT HERE: the book text. `.dockerignore` keeps `data/` and
# `sessions/` out of every layer, and the graph is filled over bolt instead --
# see `backend/scripts/push_graph.py`. An image is pushed to a registry, so
# baking two published books into one is the same mistake as committing them.

FROM python:3.12-slim

# `uv` for the install, because the lockfile is what pins this project and
# pip would resolve something else.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

# DEPENDENCIES BEFORE SOURCE, so editing a route does not reinstall spacy.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# spacy is imported at API startup and wants its model on disk. ~12MB, and a
# missing one is an ImportError at the first request rather than at build.
RUN python -m spacy download en_core_web_sm

COPY backend/ ./backend/
RUN uv sync --locked --no-editable --no-dev

# RAILWAY ASSIGNS THE PORT at run time and it is not knowable here, so this is
# a shell form that expands `$PORT`, with a local default for `docker run`.
CMD uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
