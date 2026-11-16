# ---------------------------------------------------------------------------
# astro-webui: server-rendered player (SSR). The browser only talks to this origin.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

# Build context is the repository root so the gRPC contract can be copied in.
COPY services/web/package.json services/web/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY services/web/ .
# astro.config.mjs is `output: server`; the build emits dist/server + dist/client.
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=4321

COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
# The gRPC contract is loaded at runtime by proto-loader.
COPY proto/lirify.proto ./proto/lirify.proto
ENV PROTO_PATH=/app/proto/lirify.proto

RUN addgroup -S lirify && adduser -S lirify -G lirify && chown -R lirify:lirify /app
USER lirify

EXPOSE 4321
CMD ["node", "./dist/server/entry.mjs"]
