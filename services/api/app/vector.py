"""Qdrant Cloud vector store for the lyric similarity index.

The similarity matrix is no longer persisted as a giant JSON/NPY blob: each
committed track owns one embedding in Qdrant Cloud, and recommendations are a
nearest-neighbour query around the seed track. Only python-backend holds
credentials.

Embeddings are deterministic feature hashes of the normalised lyric tokens, so
the same text always maps to the same vector without shipping a vocabulary to
Qdrant. The in-process matrix stays available as a fallback when Qdrant is not
configured, which keeps `docker compose up` working offline.
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import requests

# --- embeddings -------------------------------------------------------------
# The local indexer points LLAMA_EMBED_URL at llama-server (Qwen3-Embedding-0.6B,
# GGUF). When it is unset the deterministic hashing trick keeps `docker compose`
# and the read-only serving image working with no model at all.
LLAMA_EMBED_URL = (os.environ.get("LLAMA_EMBED_URL") or "").strip().rstrip("/")
EMBEDDING_PROVIDER = "llama.cpp" if LLAMA_EMBED_URL else "hash"
LLAMA_EMBED_MODEL = (os.environ.get("LLAMA_EMBED_MODEL") or "qwen3-embedding-0.6b").strip()
try:
    LLAMA_EMBED_BATCH = max(1, int(os.environ.get("LLAMA_EMBED_BATCH", "8")))
except ValueError:
    LLAMA_EMBED_BATCH = 8
try:
    LLAMA_EMBED_TIMEOUT = max(5, int(os.environ.get("LLAMA_EMBED_TIMEOUT", "120")))
except ValueError:
    LLAMA_EMBED_TIMEOUT = 120
# Conservative text budget: the laptop server runs with a small context so the
# KV/compute buffers stay inside 4 GB of VRAM next to the compositor.
try:
    LLAMA_EMBED_MAX_CHARS = max(256, int(os.environ.get("LLAMA_EMBED_MAX_CHARS", "6000")))
except ValueError:
    LLAMA_EMBED_MAX_CHARS = 6000

SERVE_ONLY = (os.environ.get("SERVE_ONLY", "1").strip().lower() not in {"0", "false", "no", "off"})

# Qwen3-Embedding-0.6B emits 1024-dimensional vectors. Keep 256 for the hash
# fallback so an existing collection keeps working; the local indexer uses a
# separate collection name (see docs/ARCHITECTURE.md) for the 1024-dim model.
DEFAULT_DIM = int(os.environ.get("QDRANT_VECTOR_SIZE", "1024" if LLAMA_EMBED_URL else "256"))
COLLECTION = os.environ.get("QDRANT_COLLECTION", "lirify_lyrics")
# Namespaced UUIDs are what Qdrant accepts as point ids; video ids are not UUIDs.
_POINT_NAMESPACE = uuid.UUID("6f0a1f4e-7c2b-5c6d-9f10-1b2c3d4e5f60")


class LlamaEmbedder:
    """Small OpenAI-compatible client for llama.cpp's ``/v1/embeddings``.

    Batches are intentionally tiny (default 8) because the target is an RTX 2050
    with 4 GB of VRAM shared with the compositor. A failed request is logged and
    the caller falls back to the deterministic hash vector, so indexing keeps
    moving even if the model server is restarting.
    """

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.dim = 0
        self._warned = False

    def embed(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]:
        if not texts:
            return []
        size = max(1, batch_size or LLAMA_EMBED_BATCH)
        out: List[List[float]] = []
        for start in range(0, len(texts), size):
            chunk = [text[:LLAMA_EMBED_MAX_CHARS] for text in texts[start : start + size]]
            response = self.session.post(
                f"{self.base}/v1/embeddings",
                json={"model": LLAMA_EMBED_MODEL, "input": chunk},
                timeout=LLAMA_EMBED_TIMEOUT,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"llama.cpp embeddings {response.status_code}: {response.text[:300]}"
                )
            payload = response.json() or {}
            data = payload.get("data")
            if not isinstance(data, list) or len(data) != len(chunk):
                raise RuntimeError(f"unexpected llama.cpp embeddings payload: {str(payload)[:300]}")
            # Some servers return the rows out of order; the `index` field is the
            # contract, so sort rather than trusting the list order.
            rows = sorted(data, key=lambda row: int(row.get("index", 0)))
            for row in rows:
                vector = row.get("embedding")
                if not isinstance(vector, list) or not vector:
                    raise RuntimeError("llama.cpp returned an empty embedding")
                if not self.dim:
                    self.dim = len(vector)
                out.append([float(value) for value in vector])
        return out

    def health(self) -> bool:
        try:
            response = self.session.get(f"{self.base}/health", timeout=5)
            return response.status_code < 400
        except requests.RequestException:
            return False


_LLAMA: Optional[LlamaEmbedder] = None
_LLAMA_LOCK = threading.Lock()


def get_llama_embedder() -> Optional[LlamaEmbedder]:
    global _LLAMA
    if not LLAMA_EMBED_URL:
        return None
    with _LLAMA_LOCK:
        if _LLAMA is None:
            _LLAMA = LlamaEmbedder(LLAMA_EMBED_URL)
            print(f"[lirify] embeddings via llama.cpp at {LLAMA_EMBED_URL}", flush=True)
        return _LLAMA


def embedding_dim() -> int:
    embedder = get_llama_embedder()
    if embedder is not None and embedder.dim:
        return embedder.dim
    return DEFAULT_DIM


def point_id(video_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, video_id))


def _bucket(token: str, dim: int) -> Tuple[int, float]:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    raw = int.from_bytes(digest, "big")
    return raw % dim, 1.0 if (raw >> 63) & 1 else -1.0


def embed_tokens(tokens: Iterable[str], dim: int = DEFAULT_DIM) -> List[float]:
    """Hashing-trick TF vector. Sublinear term frequency, L2 normalised."""
    counts: Dict[int, float] = {}
    for token in tokens:
        if not token:
            continue
        index, sign = _bucket(token, dim)
        counts[index] = counts.get(index, 0.0) + sign
    vector = np.zeros(dim, dtype=np.float32)
    for index, value in counts.items():
        vector[index] = np.sign(value) * (1.0 + np.log10(abs(value))) if value else 0.0
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector.tolist()


def _hash_embed_lyrics(lyrics: str, dim: int) -> List[float]:
    from main import normalize_lyrics  # local import: avoids a cycle at import time

    return embed_tokens(normalize_lyrics(lyrics or "", "en"), dim)


def embed_lyrics(lyrics: str, dim: int = DEFAULT_DIM) -> List[float]:
    """One embedding vector: llama.cpp when configured, deterministic hash else."""
    embedder = get_llama_embedder()
    if embedder is not None:
        try:
            return embedder.embed([lyrics or ""])[0]
        except Exception as exc:  # pragma: no cover - model server hiccup
            if not embedder._warned:
                embedder._warned = True
                print(
                    f"[lirify] llama.cpp embedding failed ({exc}); using the hash fallback",
                    flush=True,
                )
    return _hash_embed_lyrics(lyrics, dim)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Batch helper used by the local indexer's backfill/publish path."""
    embedder = get_llama_embedder()
    if embedder is not None:
        try:
            return embedder.embed(texts)
        except Exception as exc:  # pragma: no cover
            print(f"[lirify] llama.cpp batch failed ({exc}); hashing instead", flush=True)
    return [_hash_embed_lyrics(text, DEFAULT_DIM) for text in texts]



class VectorStore:
    backend = "none"
    dim = DEFAULT_DIM
    read_only = SERVE_ONLY

    def healthy(self) -> bool:
        return False

    def ensure(self) -> bool:
        return False

    def upsert(self, tracks: List[Dict[str, Any]]) -> int:
        return 0

    def delete(self, video_ids: List[str]) -> int:
        return 0

    def count(self) -> int:
        return 0

    def neighbours(self, video_id: str, limit: int = 10) -> List[Tuple[str, float]]:
        return []


class QdrantStore(VectorStore):
    backend = "qdrant"

    def __init__(self, url: str, api_key: str = "", dim: int = DEFAULT_DIM) -> None:
        self.base = url.rstrip("/")
        self.api_key = api_key
        self.dim = dim
        self.collection = COLLECTION
        self.read_only = SERVE_ONLY
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if api_key:
            self.session.headers.update({"api-key": api_key})
        self._ready = False

    # -- helpers ----------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base}/collections/{self.collection}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        try:
            response = self.session.request(
                method, self._url(path), timeout=float(os.environ.get("QDRANT_TIMEOUT", "15")), **kwargs
            )
        except requests.RequestException as exc:
            print(f"[lirify] qdrant request failed: {exc}", flush=True)
            return None
        if response.status_code == 404:
            self._ready = False
            return None
        if response.status_code >= 400:
            print(
                f"[lirify] qdrant {method} {path} -> {response.status_code}: {response.text[:300]}",
                flush=True,
            )
            return None
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    # -- lifecycle --------------------------------------------------------
    def healthy(self) -> bool:
        try:
            response = self.session.get(
                f"{self.base}/collections/{self.collection}", timeout=10
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def ensure(self) -> bool:
        if self._ready:
            return True
        existing = self._request("GET", "")
        if existing is None:
            # A serving replica must not create collections (or anything else):
            # only local-indexer owns Qdrant writes.
            if self.read_only:
                print(
                    f"[lirify] qdrant collection {self.collection} does not exist; "
                    "read-only serving replica will recommend from the matrix",
                    flush=True,
                )
                return False
            created = self._request(
                "PUT",
                "",
                json={"vectors": {"size": self.dim, "distance": "Cosine"}},
            )
            self._ready = created is not None
            return self._ready
        size = (
            existing.get("result", {})
            .get("config", {})
            .get("params", {})
            .get("vectors", {})
            .get("size")
        )
        if size and int(size) != self.dim:
            # The collection was created with another dimension: keep going with
            # the stored size so an env change cannot corrupt the index.
            print(
                f"[lirify] qdrant collection dimension is {size}, expected {self.dim}; "
                "using the existing dimension",
                flush=True,
            )
            self.dim = int(size)
        self._ready = True
        return True

    def count(self) -> int:
        payload = self._request("POST", "/points/count", json={"exact": True})
        if not payload:
            return 0
        return int(payload.get("result", {}).get("count", 0))

    # -- writes -----------------------------------------------------------
    def upsert(self, tracks: List[Dict[str, Any]]) -> int:
        if self.read_only:
            print("[lirify] Qdrant upsert blocked on a read-only serving replica", flush=True)
            return 0
        if not tracks or not self.ensure():
            return 0
        valid = [
            track
            for track in tracks
            if (track.get("video_id") or "") and (track.get("lyrics") or "").strip()
        ]
        if not valid:
            return 0
        # Batch the embedding calls: llama.cpp on a 4 GB GPU benefits from the
        # client-side batch far more than from one request per song.
        vectors = embed_texts([track.get("lyrics") or "" for track in valid])
        if vectors and len(vectors[0]) != self.dim:
            raise RuntimeError(
                f"embedding dimension {len(vectors[0])} does not match the Qdrant "
                f"collection {self.collection!r} dimension {self.dim}; use a new "
                "QDRANT_COLLECTION for a different embedding model"
            )
        points = []
        for track, vector in zip(valid, vectors):
            video_id = track.get("video_id") or ""
            points.append(
                {
                    "id": point_id(video_id),
                    "vector": vector,
                    "payload": {
                        "video_id": video_id,
                        "title": track.get("track") or track.get("title", ""),
                        "artist": track.get("artist", ""),
                        "language": track.get("language", ""),
                    },
                }
            )
        if not points:
            return 0
        written = 0
        # Qdrant accepts batches up to ~100 points comfortably on the free tier.
        for start in range(0, len(points), 64):
            chunk = points[start : start + 64]
            if self._request("PUT", "/points?wait=true", json={"points": chunk}) is not None:
                written += len(chunk)
        return written

    def delete(self, video_ids: List[str]) -> int:
        if self.read_only:
            return 0
        if not video_ids or not self.ensure():
            return 0
        ids = [point_id(v) for v in video_ids if v]
        self._request("POST", "/points/delete?wait=true", json={"points": ids})
        return len(ids)

    # -- reads ------------------------------------------------------------
    def neighbours(self, video_id: str, limit: int = 10) -> List[Tuple[str, float]]:
        if not video_id or not self.ensure():
            return []
        seed = self._request("GET", f"/points/{point_id(video_id)}?with_vector=true")
        if not seed:
            return []
        result = seed.get("result") or {}
        vector = result.get("vector")
        # Named-vector collections return a mapping; ours is a single vector.
        if isinstance(vector, dict):
            vector = next(iter(vector.values()), None)
        if not vector:
            return []
        payload = self._request(
            "POST",
            "/points/search",
            json={
                "vector": vector,
                "limit": max(1, min(limit + 1, 100)),
                "with_payload": True,
                "filter": {"must_not": [{"has_id": [point_id(video_id)]}]},
            },
        )
        hits = (payload or {}).get("result") or []
        out: List[Tuple[str, float]] = []
        for hit in hits:
            candidate = (hit.get("payload") or {}).get("video_id")
            if candidate:
                out.append((candidate, float(hit.get("score", 0.0))))
        return out[:limit]


class NullVectorStore(VectorStore):
    backend = "none"


_VECTORS: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _VECTORS
    if _VECTORS is not None:
        return _VECTORS
    url = (os.environ.get("QDRANT_URL") or "").strip()
    if not url:
        print(
            "[lirify] QDRANT_URL is not set; recommendations use the in-process matrix.",
            flush=True,
        )
        _VECTORS = NullVectorStore()
        return _VECTORS
    _VECTORS = QdrantStore(url, os.environ.get("QDRANT_API_KEY", "").strip(), DEFAULT_DIM)
    return _VECTORS


def reset_vector_store() -> None:
    global _VECTORS
    _VECTORS = None
