# ---------------------------------------------------------------------------
# python-backend: stateless core engine (REST + gRPC h2c on one port)
# ---------------------------------------------------------------------------
FROM caddy:2-alpine AS caddy

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    HTTP_PORT=8000 \
    GRPC_PORT=50051

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=caddy /usr/bin/caddy /usr/bin/caddy

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Caddyfile /etc/caddy/Caddyfile
COPY run.sh /run.sh
RUN chmod +x /run.sh

# No writable data directory: index state lives in MongoDB Atlas and Qdrant.
COPY app/ /app

EXPOSE 8080
CMD ["/run.sh"]
