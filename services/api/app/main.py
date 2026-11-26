"""Lirify cloud serving replica.

This process is deliberately small: it reads committed songs from MongoDB Atlas
and the pre-computed LLM embeddings from Qdrant Cloud, then answers the player
and dashboard over REST + gRPC. It never scrapes, embeds, builds matrices or
writes index state. Indexing lives in `services/local-indexer`.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from store import get_store
from vector import get_vector_store

WEIGHTS = {"name": 0.10, "artist": 0.05, "lyrics": 0.85}
JACCARD_SCOPE = "name+artist"
SERVE_ONLY = True
SERVING_MODE = "serve-only"
READ_ONLY_DETAIL = (
    "This instance serves committed state only (SERVE_ONLY=true). "
    "Indexing runs on the local-indexer stack."
)

STORE = get_store()
VECTORS = get_vector_store()

MAX_INDEXED_SONGS = int(os.environ.get("MAX_INDEXED_SONGS", "3000"))
REFRESH_SECONDS = float(os.environ.get("INDEX_REFRESH_SECONDS", "60"))
FRESHNESS_CHECK_SECONDS = float(os.environ.get("INDEX_CHECK_SECONDS", "10"))
PUBLIC_RATE_LIMIT = int(os.environ.get("PUBLIC_RATE_LIMIT_PER_MINUTE", "0"))

DURATIONS: dict[str, float] = {}
STATE: dict[str, Any] = {
    "songs": [],
    "ids": [],
    "by_id": {},
    "stats": {},
    "matrices": {},
    "build": {},
}
INDEX_LOADED = False
MONGO_ERROR = ""
STATE_REV = 0
_ERROR = ""
_LOADED_AT = 0.0
_CHECKED_AT = 0.0
_LOCK = threading.RLock()

app = FastAPI(title="Lirify API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def _stats_counts(songs: list[dict[str, Any]]) -> dict[str, int]:
    languages: dict[str, int] = {}
    backends: dict[str, int] = {}
    for song in songs:
        language = song.get("language") or "unknown"
        backend = song.get("backend") or "none"
        languages[language] = languages.get(language, 0) + 1
        backends[backend] = backends.get(backend, 0) + 1
    return {"languages": languages, "backends": backends}


def load_state() -> None:
    """Hydrate metadata from Atlas. No matrices, no embeddings, no writes."""
    global INDEX_LOADED, MONGO_ERROR, STATE_REV, _LOADED_AT
    limite = MAX_INDEXED_SONGS if MAX_INDEXED_SONGS >= 0 else None
    try:
        stored = STORE.load_songs(limit=limite)
    except Exception as exc:  # noqa: BLE001 - Atlas boundary
        MONGO_ERROR = f"{type(exc).__name__}: {exc}"
        print(f"[lirify] could not load songs: {exc}", flush=True)
        return

    songs = []
    for row in stored:
        letra = (row.get("lyrics") or "").strip()
        if not letra or row.get("backend") == "instrumental":
            continue
        songs.append(
            {
                "video_id": row.get("video_id", ""),
                "track": row.get("track") or row.get("title", ""),
                "title": row.get("title", "") or row.get("track", ""),
                "artist": row.get("artist", ""),
                "language": row.get("language", ""),
                "lyrics": row.get("lyrics", ""),
                "backend": row.get("backend", ""),
                "duration": row.get("duration"),
            }
        )

    try:
        DURATIONS.update(
            {key: float(value) for key, value in STORE.durations_all().items()}
        )
    except Exception as exc:  # noqa: BLE001 - optional cache
        print(f"[lirify] duration cache unavailable: {exc}", flush=True)

    try:
        stats = STORE.stats_get() or {}
        revision = STORE.stats_revision()
    except Exception:  # noqa: BLE001 - Atlas boundary
        stats = {}
        revision = 0

    with _LOCK:
        STATE.update(
            songs=songs,
            ids=[song["video_id"] for song in songs],
            by_id={song["video_id"]: song for song in songs},
            stats=stats,
            build={},
            matrices={},
        )
        INDEX_LOADED = True
        MONGO_ERROR = ""
        STATE_REV = int(revision)
        _LOADED_AT = time.time()
    print(
        f"[lirify] serving {len(songs)} committed songs (rev {STATE_REV}, "
        f"vectors={VECTORS.backend})",
        flush=True,
    )


def ensure_fresh_index(force: bool = False) -> None:
    global _CHECKED_AT
    if not force and (time.time() - _CHECKED_AT) < FRESHNESS_CHECK_SECONDS:
        return
    _CHECKED_AT = time.time()
    try:
        revision = STORE.stats_revision()
    except Exception:  # noqa: BLE001 - Atlas boundary
        return
    if force or revision != STATE_REV:
        load_state()


# ---------------------------------------------------------------------------
# Ranking over pre-computed LLM embeddings
# ---------------------------------------------------------------------------
def _tokens(texto: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]+", (texto or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _summary(song: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "video_id": song["video_id"],
        "title": song["track"],
        "artist": song["artist"],
        "language": song["language"],
        "score": round(float(score), 6),
    }


def search(q: str, limit: int = 20) -> dict[str, Any]:
    """Lexical search for the player; the web UI ranks with Cloudflare Workers AI."""
    ensure_fresh_index()
    query = (q or "").strip()
    limite = max(1, min(int(limit or 20), 100))
    if not query:
        return {"query": q, "results": []}

    consulta = _tokens(query)
    frase = query.lower()
    resultados: list[dict[str, Any]] = []
    for song in STATE["songs"]:
        titulo = _tokens(song["track"])
        artista = _tokens(song["artist"])
        letra = song["lyrics"].lower()
        puntaje = 0.0
        if consulta:
            puntaje += len(consulta & titulo) / len(consulta)
            puntaje += 0.6 * len(consulta & artista) / len(consulta)
            puntaje += 0.25 * min(letra.count(token) for token in consulta)
        if frase in song["track"].lower():
            puntaje += 1.0
        if frase in song["artist"].lower():
            puntaje += 0.5
        if puntaje <= 0:
            continue
        resultados.append(_summary(song, puntaje))

    resultados.sort(key=lambda row: -row["score"])
    return {"query": query, "results": resultados[:limite]}


def recommend_songs(seed_video_ids: list[str], limit: int = 10) -> dict[str, Any]:
    """Vector recommendation over the embeddings the local indexer published."""
    ensure_fresh_index()
    limite = max(1, min(int(limit or 10), 50))
    seeds = [
        video_id
        for video_id in dict.fromkeys(seed_video_ids or [])
        if video_id in STATE["by_id"]
    ]
    if not seeds:
        return {"seed_video_id": "", "recommendations": [], "engine": "none"}

    semilla = STATE["by_id"][seeds[0]]
    if VECTORS.backend == "none":
        return {
            "seed_video_id": seeds[0],
            "seed_video_ids": seeds,
            "recommendations": [],
            "engine": "none",
            "weights": WEIGHTS,
        }

    totales: dict[str, float] = {}
    for posicion, seed in enumerate(seeds[:5]):
        peso = 1.0 / (1 + posicion)
        for candidate_id, similitud in VECTORS.neighbours(seed, limite * 3):
            if candidate_id in seeds or candidate_id not in STATE["by_id"]:
                continue
            totales[candidate_id] = totales.get(candidate_id, 0.0) + peso * float(
                similitud
            )

    ranked = sorted(totales.items(), key=lambda item: -item[1])[:limite]
    recomendaciones = []
    for candidate_id, similitud in ranked:
        candidato = STATE["by_id"][candidate_id]
        puntaje = (
            WEIGHTS["lyrics"] * similitud
            + WEIGHTS["name"]
            * _jaccard(_tokens(semilla["track"]), _tokens(candidato["track"]))
            + WEIGHTS["artist"]
            * _jaccard(_tokens(semilla["artist"]), _tokens(candidato["artist"]))
        )
        recomendaciones.append(_summary(candidato, puntaje))
    return {
        "seed_video_id": seeds[0],
        "seed_video_ids": seeds,
        "recommendations": recomendaciones,
        "engine": "qdrant",
        "weights": WEIGHTS,
    }


def recommend(video_id: str, limit: int = 10, seeds: str = "") -> dict[str, Any]:
    seed_list = [video_id] + [seed.strip() for seed in seeds.split(",") if seed.strip()]
    payload = recommend_songs(seed_list, limit)
    if not payload["recommendations"] and video_id not in STATE["ids"]:
        raise HTTPException(404, "Unknown video id")
    return {"video_id": video_id, **payload}


# ---------------------------------------------------------------------------
# Stats and health
# ---------------------------------------------------------------------------
def stats_payload() -> dict[str, Any]:
    ensure_fresh_index()
    songs = STATE["songs"]
    counts = _stats_counts(songs)
    build = STATE.get("stats") or {}
    return {
        "indexed_songs": len(songs),
        "video_ids": len(songs),
        "vocabulary_size": 0,
        "inverted_terms": 0,
        "lyrics_tokens": 0,
        "languages": counts["languages"],
        "backends": counts["backends"],
        "playlist_pending": 0,
        "matrix_pending": 0,
        "failed_songs": 0,
        "cached_lyrics": 0,
        "jobs": [],
        "matrices_available": [],
        "weights": WEIGHTS,
        "generated_at": int(time.time()),
        "lyrics_providers": [],
        "top_terms": [],
        "stateless": True,
        "tracks_store": STORE.backend,
        "vectors_store": VECTORS.backend,
        "max_indexed_songs": MAX_INDEXED_SONGS,
        "serve_only": True,
        "mode": SERVING_MODE,
        "embedding_provider": "precomputed",
        "tokenizer": "",
        "jaccard_scope": JACCARD_SCOPE,
        "local_vocabulary_terms": 0,
        "local_inverted_terms": 0,
        "local_index_dir": "",
        "revision": STATE_REV,
        "embedding_model": build.get("embedding_model", ""),
        "embedding_dim": build.get("embedding_dim", 0),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mode": SERVING_MODE,
        "serve_only": True,
        "revision": STATE_REV,
        "indexed_songs": len(STATE["songs"]),
    }


@app.get("/readyz")
def readyz():
    checks = {
        "index_loaded": INDEX_LOADED,
        "store": STORE.backend,
        "mongo_error": MONGO_ERROR,
        "vectors": VECTORS.backend,
        "revision": STATE_REV,
    }
    if not INDEX_LOADED:
        return JSONResponse({"status": "loading", **checks}, status_code=503)
    return {"status": "ready", **checks}


@app.get("/stats")
@app.get("/api/stats")
def stats():
    return stats_payload()


@app.get("/queue")
def queue_status():
    return {"pending": 0, "queue": [], "mode": SERVING_MODE}


@app.get("/cache")
def cache_status():
    return {"cached_lyrics": 0, "failed_songs": 0, "mode": SERVING_MODE}


@app.get("/providers")
def providers():
    return {"providers": [], "mode": SERVING_MODE}


@app.get("/matrices")
def matrices():
    return {"matrices": [], "mode": SERVING_MODE}


@app.post("/admin/reload")
def admin_reload():
    load_state()
    return {"status": "reloaded", "revision": STATE_REV, "songs": len(STATE["songs"])}


@app.get("/search")
def search_route(q: str, limit: int = 20):
    return search(q, limit)


@app.get("/recommend/{video_id}")
def recommend_route(video_id: str, limit: int = 10, seeds: str = ""):
    return recommend(video_id, limit, seeds)


@app.get("/song/{video_id}")
def song(video_id: str):
    if video_id not in STATE["by_id"]:
        raise HTTPException(404, "Unknown video id")
    return STATE["by_id"][video_id]


@app.get("/songs")
@app.get("/tracks")
def songs(offset: int = 0, limit: int = 50, language: str = ""):
    ensure_fresh_index()
    rows = STATE["songs"]
    if language:
        rows = [row for row in rows if row["language"] == language]
    return {"total": len(rows), "songs": rows[offset : offset + limit]}


def _require_indexer(feature: str) -> None:
    raise HTTPException(403, f"{feature} is unavailable: {READ_ONLY_DETAIL}")


@app.post("/index")
async def index(_request: Request):
    _require_indexer("/index")


@app.post("/queue")
async def queue_playlists(_request: Request):
    _require_indexer("/queue")


@app.get("/extract")
def extract(_url: str = ""):
    _require_indexer("/extract")


@app.post("/retry")
def retry_failed():
    _require_indexer("/retry")


@app.api_route(
    "/api/v1/bot/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
)
async def bot_surface(path: str):
    if path == "health":
        return {"status": "ok", "mode": SERVING_MODE, "serve_only": True}
    _require_indexer(f"/api/v1/bot/{path}")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _startup() -> None:
    load_state()
    if os.environ.get("GRPC_INPROCESS", "1") != "0":
        try:
            import grpc_server

            app.state.grpc_server = await grpc_server.start_server()
        except Exception as exc:  # noqa: BLE001 - gRPC is optional at boot
            app.state.grpc_server = None
            print(f"[lirify] gRPC server not started: {exc}", flush=True)


@app.on_event("shutdown")
async def _shutdown() -> None:
    server = getattr(app.state, "grpc_server", None)
    if server is not None:
        import grpc_server

        await grpc_server.stop_server(server)


# Player routes are read-only shapers of STATE.
from player_api import build_router as _build_player_router

app.include_router(_build_player_router(lambda: STATE, search, recommend))


def refresh_loop(stop: Callable[[], bool]) -> None:
    while not stop():
        time.sleep(max(REFRESH_SECONDS, 5))
        ensure_fresh_index(force=True)
