# Standalone local indexer: owns ingestion, the core.py engine and every
# Atlas/Qdrant write. It does not import the cloud API.
#
# Build from the repository root (needs the generated gRPC stubs):
#   docker build -f services/local-indexer/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    GRPC_PORT=50051

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CPU torch by default: the image is used on hosts without the NVIDIA container
# runtime. Build with --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124
# (or your CUDA wheel index) once nvidia-container-toolkit is configured.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

COPY services/local-indexer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir torch --index-url "${TORCH_INDEX_URL}" \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -c "import nltk; nltk.download('stopwords', quiet=True)"

COPY services/api/app/lirifypb/ /app/lirifypb/
COPY services/local-indexer/core.py /app/core.py
COPY services/local-indexer/ingest.py /app/ingest.py
COPY services/local-indexer/lyrics_sources.py /app/lyrics_sources.py
COPY services/local-indexer/pipeline.py /app/pipeline.py
COPY services/local-indexer/db_admin.py /app/db_admin.py
COPY services/local-indexer/admin_api.py /app/admin_api.py
COPY services/local-indexer/local_server.py /app/local_server.py
COPY services/local-indexer/run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 50051 8080
CMD ["/run.sh"]
