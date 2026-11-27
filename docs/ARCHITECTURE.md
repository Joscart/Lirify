# Lirify architecture

Lirify is split into two independent stacks that share one gRPC contract and one
pair of databases:

* **Cloud serving** — read-only: `python-backend`, `go-webui`, `astro-webui`.
  They read committed songs from MongoDB Atlas and pre-computed LLM embeddings
  from Qdrant Cloud. They never scrape, embed, build matrices or write state.
* **Local indexing** — the standalone `local-indexer`, which owns ingestion, the
  `core.py` engine and every Atlas/Qdrant write. It does not call the cloud API
  and the cloud API does not call it.

```
CLOUD (read-only, three services)
                     ┌──────────────────────────────┐
  browser ──HTTPS───▶│ astro-webui   (Cloud Run)    │
                     │  search → Cloudflare Workers AI (+ gRPC Search)
                     │  radio  → gRPC Recommend (Qdrant embeddings)
                     │  player → gRPC + /api/player proxy
                     └───────────────┬──────────────┘
                                     │ gRPC / TLS :443
  browser ──HTTPS───▶┌───────────────▼──────────────┐
                     │ go-webui      (Cloud Run)    │
                     │  read-only dashboard         │
                     │  stats · tracks · jobs       │
                     └───────────────┬──────────────┘
                                     │ gRPC
                     ┌───────────────▼──────────────┐
                     │ python-backend (Cloud Run)   │
                     │  SERVE_ONLY=true             │
                     │  no matrices, no workers     │
                     │  Atlas songs  ·  Qdrant vecs │
                     └───────────────▲──────────────┘
                                     │ writes
LOCAL (laptop)                       │
  local-ui (Go, :8090) ──gRPC──▶ local-indexer (Python, :50051)
                                   │  ingest → core.py → embeddings
                                   │  Atlas songs · Qdrant vectors
                                   └── core.py owns:
                                       terms, inverted index, TF-IDF,
                                       Qwen3-Embedding-0.6B vectors,
                                       search / recommend, publish
```

## Service boundaries

| Service | Owns | Never touches |
| --- | --- | --- |
| `python-backend` | read-only serving of committed songs + pre-computed vectors; player proxy; revision checks | ingestion, embeddings, matrices, index writes |
| `astro-webui` | SSR + player; Cloudflare Workers AI query understanding | Mongo, Qdrant, index state |
| `go-webui` | read-only dashboard: stats, jobs, tracks, index health | Mongo, Qdrant, local disk, write RPCs |
| `local-indexer` | scrape → lyrics → `core.py` index → embeddings → Atlas/Qdrant | the browser, HTTP, the cloud API |
| `local-ui` | the same dashboard plus index/publish controls; gRPC only | databases, business logic |
| browser | listening history, search history, playback session | any database |

## `core.py` — the single engine

`services/local-indexer/core.py` is the only implementation of the index:

| Area | Functions |
| --- | --- |
| Text | `normalizar_texto`, `tokenizar_texto`, `eliminar_stopwords`, `aplicar_stemming`, `procesar_texto` (one flat term list) |
| Index | `agregar_documento`, `agregar_cancion`, `indexar_canciones`, `construir_matriz_*`, `reconstruir_documento` |
| Embeddings | `construir_matriz_embeddings_llm`, `agregar_documento_con_embeddings` (Qwen3-Embedding-0.6B via sentence-transformers) |
| Query | `buscar(consulta, limite)`, `recomendar(video_ids, limite)` |
| Stats | `estadisticas()` |
| Persistence | `a_diccionario`, `desde_diccionario`, `guardar`, `cargar`, `publicar` |

`publicar()` is the only cloud write path: it upserts songs into Atlas and LLM
embeddings into Qdrant, then bumps `index_stats.revision`. **No matrix is ever
written to a database.** Tests live in `services/local-indexer/tests/test_core.py`
and run offline with a deterministic fake encoder.

## Search on the web

The query is embedded with the **same Qwen3-Embedding-0.6B model** that indexes
the lyrics, so query vectors and document vectors share one space:

1. The browser calls Astro `/api/player/search?q=…`.
2. Astro runs gRPC `Search` (with `SEMANTIC_SEARCH=true` it sends the raw query;
   otherwise Cloudflare Workers AI may expand it into 1–3 keywords).
3. `python-backend` embeds the text with a 1024-dim vector:
   - `QUERY_EMBED_URL/db/embed` (the local indexer's admin app) when configured,
   - otherwise Cloudflare Workers AI
     `@cf/qwen/qwen3-embedding-0.6b` (`CF_ACCOUNT_ID` + `CF_API_TOKEN`).
4. It searches Qdrant with that vector and blends `.85` cosine + `.10` title /
   `.05` artist Jaccard.

Without `QUERY_EMBED_URL`, `Search` falls back to lexical matching over titles,
artists and lyrics. Without Cloudflare credentials the web route simply skips
keyword expansion.

## Recommendations

1. The browser sends up to five newest ids from `localStorage`.
2. Astro calls `Recommend` over gRPC.
3. `python-backend` averages Qdrant cosine neighbours per seed and blends the
   title/artist Jaccard terms:

```python
WEIGHTS = {"name": 0.10, "artist": 0.05, "lyrics": 0.85}
score = .85 * qdrant_similarity + .10 * jaccard(title) + .05 * jaccard(artist)
```

There is no matrix fallback in the cloud: when Qdrant is empty the response is
`engine: "none"` and the player shows no recommendations. Run the local indexer
and publish once to populate the vectors.

## Where state lives

| State | Home | Writer |
| --- | --- | --- |
| Committed tracks (title, artist, lyrics, language) | Atlas `songs` | `local-indexer` |
| Index statistics + `revision` | Atlas `index_stats` | `local-indexer` |
| Resolved media durations | Atlas `media_durations` | `python-backend` (player metadata only) |
| Qwen3-Embedding-0.6B vectors (1024-dim) | Qdrant `lirify_lyrics_qwen3` | `local-indexer` |
| In-memory terms / TF-IDF / similarity | process memory of `local-indexer` | rebuilt by `core.py` |
| Listening/search history, playback clock | browser `localStorage` | browser |

Nothing is written to disk by any container. There are no vocabulary or
inverted-index files: `core.py` keeps them in memory and the cloud never needs
them.

## gRPC surface

`proto/lirify.proto` is still the single contract, generated into Python, Go and
TypeScript by `scripts/gen_proto.sh` and drift-checked in CI.

| Call | Consumer | Cloud behaviour |
| --- | --- | --- |
| `Search`, `Recommend`, `GetTrack`, `ListTracks`, `GetLyrics`, `Stream` | astro | served from songs + Qdrant |
| `GetIndexStats`, `WatchIndexStats`, `GetFailedSongs`, `MatrixPreview` | go-webui | read-only; matrices are empty in the cloud |
| `IndexPlaylist`, `QueuePlaylists`, `ExtractVideoIds`, `RetryFailed`, `IndexPlaylistFromBot` | local-ui, agents | `UNIMPLEMENTED` in the cloud |
| `LirifyIndexerService.PublishToCloud` / `GetLocalIndex` | local-ui | only registered by `local-indexer` |

The local indexer implements the read RPCs too, so the same dashboard binary
works against either target (`DASHBOARD_MODE=local` adds the controls).

## Local database admin

`local-indexer` also exposes a small HTTP admin app (`admin_api.py` →
`db_admin.py`) used by the **Databases** panel in `local-ui`:

| Route | Effect |
| --- | --- |
| `GET/POST/PUT/DELETE /db/songs…` | Atlas song CRUD (keeps the in-memory index and the Qdrant point in sync) |
| `GET /db/vectors`, `DELETE /db/vectors/{id}`, `POST /db/vectors/{id}/embed` | Qdrant point CRUD / single re-embed |
| `POST /db/vectors/rebuild` | Re-embed every Atlas song over the current collection |
| `POST /db/vectors/reset` | Drop the collection, reload from Atlas, re-embed from zero |
| `POST /db/index/reload` | Drop the in-memory index and rehydrate terms from Atlas |

go-ui proxies these under `/api/db/*` in local mode (`ADMIN_API_URL`). The admin
port is bound to `127.0.0.1:8082` on the host and is never part of the cloud
deployment.

## Health and routes

`python-backend` owns `/health` (liveness), `/readyz` (index hydrated), `/stats`,
`/search`, `/recommend/{id}`, `/song/{id}`, `/songs`, `/tracks` and the read-only
player API. Index routes answer `403`. `go-webui` exposes `/api/stats`,
`/api/queue`, `/api/cache`, `/api/tracks`, `/api/events` and the readonly
`/api/*` surface; `/health` is always `200` and `/readyz` probes python-backend.

## Invariants

- The index is accumulative: jobs add tracks, they never reset the library.
- A track is committed only with non-empty lyrics; any language is indexable.
- Duplicates are skipped per `video_id`.
- Only LLM embeddings are published to the cloud; matrices stay in the local
  process.
- `index_stats.revision` is bumped once per publish; the cloud replica re-reads
  songs when it changes.
- A capped load never prunes.
