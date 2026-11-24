# ---------------------------------------------------------------------------
# local-indexer: full indexing pipeline + publish to Atlas/Qdrant (gRPC only).
#
# Build context is the repository root so the shared python-backend modules are
# copied in unchanged:
#   docker build -f services/local-indexer/Dockerfile .
# ---------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVE_ONLY=0 \
    GRPC_INPROCESS=0 \
    GRPC_PORT=50051 \
    LOCAL_INDEX_DIR=/data/local-index

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Shared runtime (FastAPI is only needed because main.py imports it at module
# import; no HTTP server is started here) plus the tokenizer extras.
COPY services/api/requirements.txt /tmp/requirements-api.txt
COPY services/local-indexer/requirements.txt /tmp/requirements-local.txt
RUN pip install --no-cache-dir -r /tmp/requirements-api.txt -r /tmp/requirements-local.txt

# One copy of the pipeline: the same main.py / store.py / vector.py / gRPC
# adapters the serving image uses, so indexing rules cannot drift.
COPY services/api/app/ /app/
COPY services/local-indexer/local_store.py /app/local_store.py
COPY services/local-indexer/local_server.py /app/local_server.py
COPY services/local-indexer/run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 50051
CMD ["/run.sh"]
