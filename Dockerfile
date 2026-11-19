# Coraxis backend — FastAPI API server.
# Runs on Hugging Face Spaces (Docker), Cloud Run, Render, or any Docker host.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Hugging Face Spaces containers run as uid 1000; create that user so the
# same image also works on hosts that run as root.
RUN useradd -m -u 1000 user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

COPY --chown=user pyproject.toml requirements.txt README.md alembic.ini ./
COPY --chown=user src ./src

# Editable install is load-bearing: `coraxis init` locates alembic.ini
# relative to the source tree, and alembic.ini uses paths relative to the
# repo root, so the package must stay linked to this source layout.
RUN pip install --upgrade pip && pip install -e ".[postgres]"

USER user

# SQLite + Chroma live under the (writable) app dir by default. On hosts
# with an ephemeral filesystem these reset on rebuild — set
# CORAXIS_DATABASE_URL to a Postgres URL (e.g. Neon) for durable accounts.
ENV CORAXIS_HOST=0.0.0.0 \
    CORAXIS_DATABASE_URL=sqlite+aiosqlite:////home/user/app/data/coraxis.db \
    CORAXIS_CHROMA_PATH=/home/user/app/data/chroma_db
RUN mkdir -p /home/user/app/data

EXPOSE 7860

# Hosts inject $PORT (Cloud Run, Render). HF Spaces serves port 7860.
CMD ["sh", "-c", "coraxis init && coraxis serve --port ${PORT:-7860}"]
