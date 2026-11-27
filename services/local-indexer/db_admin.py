"""CRUD and maintenance for the two cloud databases used by the local indexer.

MongoDB Atlas owns the songs; Qdrant owns the pre-computed LLM embeddings. This
module is only reachable from the local dashboard (go-ui proxies to the admin
HTTP surface), and it is the only place where a song can be edited or removed
outside of a playlist run.

Mutating a song keeps three things consistent:

1. the Atlas document (camelCase, schemaVersion, timestamps),
2. the in-memory `core.Indexer` (terms, metadata, embedding row),
3. the Qdrant point (vector + payload).

`resetear_vectores()` is the "from zero" operation: it drops the Qdrant
collection, rebuilds the in-memory index from Atlas and re-embeds every song.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import core
import requests

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class DbError(RuntimeError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _mongo_uri() -> str:
    return (os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or "").strip()


def _db_name() -> str:
    return (os.environ.get("MONGODB_DB") or "lirify").strip()


def _qdrant_url() -> str:
    return (os.environ.get("QDRANT_URL") or "").strip().rstrip("/")


def _qdrant_key() -> str:
    return (os.environ.get("QDRANT_API_KEY") or "").strip()


def _collection() -> str:
    return (os.environ.get("QDRANT_COLLECTION") or "lirify_lyrics_qwen3").strip()


def _cancion_de_documento(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": doc.get("videoId", ""),
        "title": doc.get("youtubeTitle") or doc.get("title", ""),
        "track": doc.get("title", ""),
        "artist": doc.get("artist", ""),
        "language": doc.get("language", ""),
        "lyrics": doc.get("lyrics", ""),
        "backend": doc.get("backend", ""),
        "duration": doc.get("duration"),
        "created_at": doc.get("createdAt"),
        "updated_at": doc.get("updatedAt"),
    }


def _documento_de_cancion(cancion: dict[str, Any]) -> dict[str, Any]:
    ahora = time.time()
    return {
        "videoId": cancion["video_id"],
        "title": cancion["track"] or cancion["title"],
        "youtubeTitle": cancion["title"],
        "artist": cancion["artist"],
        "language": cancion["language"],
        "lyrics": cancion["lyrics"],
        "backend": cancion["backend"],
        "duration": cancion["duration"],
        "schemaVersion": 1,
        "updatedAt": ahora,
    }


def _normalizar(payload: dict[str, Any], video_id: str | None = None) -> dict[str, Any]:
    video = str(payload.get("video_id") or video_id or "").strip()
    if not VIDEO_ID_RE.fullmatch(video):
        raise DbError("video_id must be an 11-character YouTube id", 400)

    letra = str(payload.get("lyrics") or "")
    if not letra.strip():
        raise DbError("lyrics is required: only songs with lyrics are indexed", 400)

    titulo = str(payload.get("title") or payload.get("track") or "").strip()
    track = str(payload.get("track") or payload.get("title") or "").strip()
    if not track:
        raise DbError("title is required", 400)

    duracion = payload.get("duration")
    try:
        duracion = float(duracion) if duracion not in (None, "") else None
    except (TypeError, ValueError):
        duracion = None

    return {
        "video_id": video,
        "title": titulo or track,
        "track": track,
        "artist": str(payload.get("artist") or "").strip(),
        "language": str(payload.get("language") or "unknown").strip() or "unknown",
        "lyrics": letra,
        "backend": str(payload.get("backend") or "manual").strip() or "manual",
        "duration": duracion,
    }


class DbAdmin:
    def __init__(self, pipeline: Any) -> None:
        self.pipeline = pipeline

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------
    def _requerir_mongo(self) -> None:
        if not _mongo_uri():
            raise DbError("MONGODB_URI is not configured", 503)

    def _mongo(self):
        from pymongo import MongoClient

        uri = _mongo_uri()
        if not uri:
            raise DbError("MONGODB_URI is not configured", 503)
        cliente = MongoClient(uri, serverSelectionTimeoutMS=10000)
        return cliente, cliente[_db_name()]

    def _qdrant_headers(self) -> dict[str, str]:
        cabeceras = {"Content-Type": "application/json"}
        key = _qdrant_key()
        if key:
            cabeceras["api-key"] = key
        return cabeceras

    def _qdrant(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        base = _qdrant_url()
        if not base:
            return None
        url = f"{base}/collections/{_collection()}{path}"
        respuesta = requests.request(
            method,
            url,
            headers=self._qdrant_headers(),
            timeout=float(os.environ.get("QDRANT_TIMEOUT", "20")),
            **kwargs,
        )
        if respuesta.status_code == 404:
            return None
        if respuesta.status_code >= 400:
            raise DbError(
                f"Qdrant {method} {path} -> {respuesta.status_code}: "
                f"{respuesta.text[:300]}",
                502,
            )
        if not respuesta.content:
            return {}
        return respuesta.json()

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        cliente, base = self._mongo()
        try:
            mongo_total = int(base["songs"].count_documents({}))
            stats = base["index_stats"].find_one({"_id": "global"}) or {}
        finally:
            cliente.close()

        coleccion = self._qdrant("GET", "")
        qdrant: dict[str, Any] = {
            "url": _qdrant_url(),
            "collection": _collection(),
            "reachable": bool(_qdrant_url()),
            "exists": coleccion is not None,
            "points": 0,
            "dim": 0,
            "distance": "",
        }
        if coleccion:
            resultado = coleccion.get("result") or {}
            qdrant["points"] = int(resultado.get("points_count") or 0)
            vectores = (resultado.get("config") or {}).get("params", {}).get(
                "vectors"
            ) or {}
            qdrant["dim"] = int(vectores.get("size") or 0)
            qdrant["distance"] = str(vectores.get("distance") or "")

        indice = self.pipeline.indexer
        return {
            "mongo": {
                "database": _db_name(),
                "songs": mongo_total,
                "revision": int(stats.get("revision") or 0),
                "updated_at": stats.get("updatedAt"),
            },
            "qdrant": qdrant,
            "embedding": {
                "model": indice.modelo_id,
                "dim": indice.dimension_embeddings,
            },
            "index": {
                "songs": len(indice.docs_id),
                "terms": len(indice.vocabulary),
                "embeddings": 0
                if indice.matriz_embeddings_llm is None
                else int(indice.matriz_embeddings_llm.shape[0]),
            },
        }

    # ------------------------------------------------------------------
    # MongoDB CRUD
    # ------------------------------------------------------------------
    def listar_canciones(
        self, offset: int = 0, limit: int = 50, consulta: str = ""
    ) -> dict[str, Any]:
        offset = max(0, int(offset or 0))
        limit = max(1, min(int(limit or 50), 200))
        filtro: dict[str, Any] = {}
        texto = (consulta or "").strip()
        if texto:
            patron = re.escape(texto)
            filtro = {
                "$or": [
                    {"videoId": {"$regex": patron, "$options": "i"}},
                    {"title": {"$regex": patron, "$options": "i"}},
                    {"artist": {"$regex": patron, "$options": "i"}},
                ]
            }
        cliente, base = self._mongo()
        try:
            total = int(base["songs"].count_documents(filtro))
            cursor = (
                base["songs"]
                .find(filtro, {"_id": 0})
                .sort("updatedAt", -1)
                .skip(offset)
                .limit(limit)
            )
            canciones = [_cancion_de_documento(doc) for doc in cursor]
        finally:
            cliente.close()
        return {"total": total, "offset": offset, "limit": limit, "songs": canciones}

    def obtener_cancion(self, video_id: str) -> dict[str, Any]:
        cliente, base = self._mongo()
        try:
            doc = base["songs"].find_one({"videoId": video_id}, {"_id": 0})
        finally:
            cliente.close()
        if not doc:
            raise DbError("song not found", 404)
        return _cancion_de_documento(doc)

    def crear_cancion(self, payload: dict[str, Any]) -> dict[str, Any]:
        cancion = _normalizar(payload)
        documento = _documento_de_cancion(cancion)
        cliente, base = self._mongo()
        try:
            if base["songs"].find_one({"videoId": cancion["video_id"]}, {"_id": 1}):
                raise DbError("song already exists", 409)
            documento["createdAt"] = documento["updatedAt"]
            base["songs"].insert_one(documento)
        finally:
            cliente.close()

        with self.pipeline._lock:
            self.pipeline.indexer.indexar_canciones([cancion])
        self._upsertir_punto(cancion)
        return self.obtener_cancion(cancion["video_id"])

    def actualizar_cancion(
        self, video_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        cancion = _normalizar(payload, video_id=video_id)
        documento = _documento_de_cancion(cancion)
        cliente, base = self._mongo()
        try:
            resultado = base["songs"].update_one(
                {"videoId": video_id},
                {
                    "$set": documento,
                    "$setOnInsert": {"createdAt": documento["updatedAt"]},
                },
                upsert=True,
            )
        finally:
            cliente.close()
        if resultado.matched_count == 0 and resultado.upserted_id is None:
            raise DbError("song not found", 404)

        with self.pipeline._lock:
            indice = self.pipeline.indexer
            if not indice.actualizar_cancion(cancion):
                indice.indexar_canciones([cancion])
            else:
                id_documento = indice.id_de(video_id)
                if (
                    id_documento is not None
                    and indice.matriz_embeddings_llm is not None
                ):
                    indice.agregar_documento_con_embeddings(id_documento)
        self._upsertir_punto(cancion)
        return self.obtener_cancion(video_id)

    def eliminar_cancion(self, video_id: str) -> dict[str, Any]:
        cliente, base = self._mongo()
        try:
            resultado = base["songs"].delete_one({"videoId": video_id})
        finally:
            cliente.close()
        if resultado.deleted_count == 0:
            raise DbError("song not found", 404)
        with self.pipeline._lock:
            self.pipeline.indexer.eliminar_cancion(video_id)
        self._eliminar_punto(video_id)
        return {"deleted": True, "video_id": video_id}

    # ------------------------------------------------------------------
    # Qdrant CRUD
    # ------------------------------------------------------------------
    def listar_vectores(
        self, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        cuerpo: dict[str, Any] = {
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if cursor:
            cuerpo["offset"] = cursor
        payload = self._qdrant("POST", "/points/scroll", json=cuerpo)
        if payload is None:
            return {"total": 0, "points": [], "next": None, "reachable": False}
        resultado = payload.get("result") or {}
        puntos = []
        for punto in resultado.get("points") or []:
            meta = punto.get("payload") or {}
            puntos.append(
                {
                    "id": punto.get("id"),
                    "video_id": meta.get("video_id", ""),
                    "title": meta.get("title", ""),
                    "artist": meta.get("artist", ""),
                    "language": meta.get("language", ""),
                }
            )
        return {
            "points": puntos,
            "next": resultado.get("next_page_offset"),
            "reachable": True,
        }

    def reembeber(self, video_id: str) -> dict[str, Any]:
        cancion = self.obtener_cancion(video_id)
        self._upsertir_punto(cancion)
        return {"video_id": video_id, "embedded": True}

    def eliminar_vector(self, video_id: str) -> dict[str, Any]:
        self._eliminar_punto(video_id)
        return {"deleted": True, "video_id": video_id}

    # ------------------------------------------------------------------
    # Query embeddings (same model as indexing)
    # ------------------------------------------------------------------
    def embeber_textos(self, textos: list[str]) -> dict[str, Any]:
        limpios = [str(texto or "") for texto in textos][:16]
        if not limpios:
            raise DbError("texts is required", 400)
        with self.pipeline._lock:
            vectores = [
                self.pipeline.indexer.embedding_de_texto(texto) for texto in limpios
            ]
        return {
            "model": self.pipeline.indexer.modelo_id,
            "dim": len(vectores[0]),
            "provider": "sentence-transformers",
            "vectors": vectores,
        }

    def buscar_semantico(self, consulta: str, limite: int = 20) -> dict[str, Any]:
        texto = (consulta or "").strip()
        if not texto:
            raise DbError("query is required", 400)
        limite = max(1, min(int(limite or 20), 100))
        if not _qdrant_url():
            raise DbError("QDRANT_URL is not configured", 503)

        with self.pipeline._lock:
            vector = self.pipeline.indexer.embedding_de_texto(texto)
        payload = self._qdrant(
            "POST",
            "/points/search",
            json={
                "vector": vector,
                "limit": limite,
                "with_payload": True,
                "with_vector": False,
            },
        )
        resultados = []
        for hit in (payload or {}).get("result") or []:
            meta = hit.get("payload") or {}
            resultados.append(
                {
                    "video_id": meta.get("video_id", ""),
                    "title": meta.get("title", ""),
                    "artist": meta.get("artist", ""),
                    "language": meta.get("language", ""),
                    "score": round(float(hit.get("score") or 0), 6),
                }
            )
        return {
            "query": texto,
            "results": resultados,
            "engine": "embeddings",
            "model": self.pipeline.indexer.modelo_id,
        }

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def reconstruir_vectores(self) -> dict[str, Any]:
        self._requerir_mongo()
        self.pipeline.reiniciar_indice()
        return self.pipeline.publicar()

    def resetear_vectores(self) -> dict[str, Any]:
        """Drop the collection and recreate every vector from Atlas."""
        self._requerir_mongo()
        self._borrar_coleccion()
        cargadas = self.pipeline.reiniciar_indice()
        if cargadas == 0:
            self._crear_coleccion_vacia()
            return {
                "reset": True,
                "songs": 0,
                "vectors": 0,
                "message": "Collection recreated empty: there are no songs in Atlas",
            }
        resultado = self.pipeline.publicar()
        resultado["reset"] = True
        return resultado

    def reiniciar_indice(self) -> dict[str, Any]:
        self._requerir_mongo()
        cargadas = self.pipeline.reiniciar_indice()
        return {"indexed": cargadas}

    def _borrar_coleccion(self) -> None:
        if not _qdrant_url():
            raise DbError("QDRANT_URL is not configured", 503)
        base = _qdrant_url()
        respuesta = requests.delete(
            f"{base}/collections/{_collection()}",
            headers=self._qdrant_headers(),
            timeout=30,
        )
        if respuesta.status_code not in (200, 202, 404):
            raise DbError(
                f"Qdrant drop -> {respuesta.status_code}: {respuesta.text[:300]}", 502
            )

    def _crear_coleccion_vacia(self) -> None:
        base = _qdrant_url()
        respuesta = requests.put(
            f"{base}/collections/{_collection()}",
            headers=self._qdrant_headers(),
            json={
                "vectors": {
                    "size": self.pipeline.indexer.dimension_embeddings,
                    "distance": "Cosine",
                }
            },
            timeout=30,
        )
        if respuesta.status_code >= 400:
            raise DbError(
                f"Qdrant create -> {respuesta.status_code}: {respuesta.text[:300]}",
                502,
            )

    def _upsertir_punto(self, cancion: dict[str, Any]) -> None:
        if not _qdrant_url():
            return
        with self.pipeline._lock:
            vector = self.pipeline.indexer.embedding_de_texto(cancion["lyrics"])
        punto = {
            "id": core.id_punto(cancion["video_id"]),
            "vector": vector,
            "payload": {
                "video_id": cancion["video_id"],
                "title": cancion["track"],
                "artist": cancion["artist"],
                "language": cancion["language"],
            },
        }
        if self._qdrant("GET", "") is None:
            self._crear_coleccion_vacia()
        self._qdrant("PUT", "/points?wait=true", json={"points": [punto]})

    def _eliminar_punto(self, video_id: str) -> None:
        if not _qdrant_url():
            return
        self._qdrant(
            "POST",
            "/points/delete?wait=true",
            json={"points": [core.id_punto(video_id)]},
        )
