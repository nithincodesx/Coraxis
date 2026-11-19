# Coraxis backend — FastAPI API server
# Build:  docker build -t coraxis-api .
# Run:    docker run -p 8000:8000 -e CORAXIS_SECRET_KEY=<secret> coraxis-api
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# SQLite lives here by default; mount a volume at /data for persistence,
# or set CORAXIS_DATABASE_URL to a Postgres URL.
ENV CORAXIS_DATABASE_URL=sqlite+aiosqlite:////data/coraxis.db \
    CORAXIS_HOST=0.0.0.0 CORAXIS_PORT=8000
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

# Apply migrations, then serve. Single worker: the run/event state and
# rate limiter are in-process (see AUDIT.md), so do not add --workers.
CMD ["sh", "-c", "coraxis init && coraxis serve"]
