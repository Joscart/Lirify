# ---------------------------------------------------------------------------
# go-webui: stateless playlist indexer dashboard (gRPC client)
# ---------------------------------------------------------------------------
FROM golang:1.22-alpine AS build
WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .
# CGO off keeps the binary static and the runtime image tiny.
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /ui .

FROM alpine:3.20
# ca-certificates are required for the TLS gRPC channel to Cloud Run (:443).
RUN apk add --no-cache ca-certificates && adduser -D -u 65532 lirify

COPY --from=build /ui /ui

USER 65532
EXPOSE 8080
CMD ["/ui"]
