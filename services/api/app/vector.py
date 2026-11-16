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
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import requests

DEFAULT_DIM = int(os.environ.get("QDRANT_VECTOR_SIZE", "256"))
COLLECTION = os.environ.get("QDRANT_COLLECTION", "lirify_lyrics")
# Namespaced UUIDs are what Qdrant accepts as point ids; video ids are not UUIDs.
_POINT_NAMESPACE = uuid.UUID("6f0a1f4e-7c2b-5c6d-9f10-1b2c3d4e5f60")


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


def embed_lyrics(lyrics: str, dim: int = DEFAULT_DIM) -> List[float]:
    from main import normalize_lyrics  # local import: avoids a cycle at import time

    return embed_tokens(normalize_lyrics(lyrics or "", "en"), dim)


class VectorStore:
    backend = "none"
    dim = DEFAULT_DIM

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
        if not tracks or not self.ensure():
            return 0
        points = []
        for track in tracks:
            video_id = track.get("video_id") or ""
            lyrics = track.get("lyrics") or ""
            if not video_id or not lyrics.strip():
                continue
            points.append(
                {
                    "id": point_id(video_id),
                    "vector": embed_lyrics(lyrics, self.dim),
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
