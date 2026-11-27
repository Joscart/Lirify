"""Local indexing pipeline: ingest -> core.Indexer -> Atlas + Qdrant.

There is no HTTP surface and no dependency on the cloud API. One playlist runs
at a time, the index is accumulative, and publishing writes only songs (Atlas)
and LLM embeddings (Qdrant).
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from collections import deque
from typing import Any

import core
import ingest
import numpy as np


def _bandera(nombre: str, defecto: str = "1") -> bool:
    return os.environ.get(nombre, defecto).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


class Pipeline:
    def __init__(self) -> None:
        self.indexer = core.Indexer()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.orden: deque[str] = deque()
        self._lock = threading.RLock()
        self._cola = asyncio.Lock()
        self.revision = 0
        self.publicado_en = 0
        self.ultimo_error = ""
        self.arrancado_en = time.time()
        self.tareas: set[asyncio.Task] = set()
        self.auto_publicar = _bandera("PUBLISH_ON_INDEX", "1")

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    async def arrancar(self) -> None:
        if _bandera("LOAD_ON_START", "1"):
            try:
                await asyncio.to_thread(self.cargar_desde_atlas)
            except (OSError, RuntimeError, ValueError) as exc:
                self.ultimo_error = f"load failed: {exc}"
                print(f"[lirify] could not load songs from Atlas: {exc}", flush=True)

    async def detener(self) -> None:
        for tarea in list(self.tareas):
            tarea.cancel()
        self.tareas.clear()

    # ------------------------------------------------------------------
    # Indexación
    # ------------------------------------------------------------------
    async def encolar(
        self, url: str, limite: int | None = None, source: str = "local-ui"
    ) -> dict[str, Any]:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        ahora = int(time.time())
        job = {
            "job_id": job_id,
            "action": "index",
            "url": url,
            "status": "queued",
            "stage": "queued",
            "error": "",
            "added": 0,
            "attempts": 0,
            "source": source,
            "created_at": ahora,
            "updated_at": ahora,
            "error_code": "",
            "retry_mode": "agent-jitter",
        }
        self.jobs[job_id] = job
        self.orden.append(job_id)
        tarea = asyncio.create_task(self._procesar(job_id, url, limite))
        self.tareas.add(tarea)
        tarea.add_done_callback(self.tareas.discard)
        return dict(job)

    async def _procesar(self, job_id: str, url: str, limite: int | None) -> None:
        job = self.jobs[job_id]
        async with self._cola:
            self._actualizar(job, status="indexing", stage="scrape")
            try:
                canciones = await asyncio.to_thread(
                    ingest.cargar_playlist,
                    url,
                    limite,
                    lambda etapa, **campos: self._progreso(job, etapa, campos),
                )
                if not canciones:
                    self._actualizar(
                        job,
                        status="skipped",
                        stage="scrape",
                        error="No song with lyrics was found",
                    )
                    return

                self._actualizar(job, status="indexing", stage="index")
                agregados = await asyncio.to_thread(self._indexar_lote, canciones)
                self._actualizar(
                    job,
                    status="committed",
                    stage="index",
                    added=len(agregados),
                )

                if self.auto_publicar and agregados:
                    self._actualizar(job, stage="publish")
                    with self._lock:
                        nuevos = {
                            self.indexer.ids[id_documento] for id_documento in agregados
                        }
                    lote = [
                        cancion
                        for cancion in canciones
                        if str(cancion.get("video_id") or "") in nuevos
                    ]
                    await asyncio.to_thread(self.publicar, solo=lote)
                    self._actualizar(job, stage="published")
            except Exception as exc:  # noqa: BLE001 - job boundary
                self.ultimo_error = f"{type(exc).__name__}: {exc}"
                self._actualizar(
                    job,
                    status="error",
                    stage="error",
                    error=str(exc)[:800],
                    error_code=self._codigo_error(str(exc)),
                )
        self._finalizar_job(job)

    def _indexar_lote(self, canciones: list[dict[str, Any]]) -> list[int]:
        with self._lock:
            return self.indexer.indexar_canciones(canciones)

    def _progreso(
        self, job: dict[str, Any], etapa: str, campos: dict[str, Any]
    ) -> None:
        if etapa == "extract":
            self._actualizar(job, stage="extract", error=job.get("error") or "")
        elif etapa == "scraped":
            self._actualizar(job, stage="matrix")
        else:
            self._actualizar(job, stage=etapa)

    def _actualizar(self, job: dict[str, Any], **campos: Any) -> None:
        job.update(campos)
        job["updated_at"] = int(time.time())

    def _finalizar_job(self, job: dict[str, Any]) -> None:
        if job["job_id"] in self.orden:
            self.orden.remove(job["job_id"])
        job["updated_at"] = int(time.time())

    @staticmethod
    def _codigo_error(mensaje: str) -> str:
        texto = mensaje.lower()
        if "private" in texto:
            return "private_playlist"
        if "not found" in texto or "does not exist" in texto:
            return "not_found"
        if "bot" in texto or "sign in" in texto:
            return "bot_check"
        if "rate" in texto and "limit" in texto:
            return "rate_limited"
        if "yt-dlp" in texto:
            return "network_error"
        return "index_failed"

    # ------------------------------------------------------------------
    # Publicación
    # ------------------------------------------------------------------
    def publicar(
        self, lote: int = 64, solo: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if not self.indexer.docs_id:
                raise RuntimeError("Nothing indexed yet")
            if solo is None and self.indexer.matriz_embeddings_llm is None:
                self.indexer.construir_matriz_embeddings_llm()
            resultado = self.indexer.publicar(lote=lote, solo=solo)
            self.revision = int(resultado.get("revision") or 0)
            self.publicado_en = int(time.time())
            print(
                f"[lirify] published {resultado['songs']} songs to "
                f"{resultado['database']} and {resultado['vectors']} vectors "
                f"(revision {self.revision})",
                flush=True,
            )
            return resultado

    def cargar_desde_atlas(self, limite: int | None = None) -> int:
        """Hydrate the in-memory index from Atlas (songs are the source of truth)."""
        import re

        from pymongo import MongoClient

        uri = (
            os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or ""
        ).strip()
        if not uri:
            return 0
        base = MongoClient(uri, serverSelectionTimeoutMS=15000)[
            os.environ.get("MONGODB_DB") or "lirify"
        ]
        consulta = base["songs"].find(
            {},
            {
                "_id": 0,
                "videoId": 1,
                "title": 1,
                "artist": 1,
                "language": 1,
                "lyrics": 1,
                "backend": 1,
            },
        )
        if limite:
            consulta = consulta.limit(limite)

        canciones = []
        for documento in consulta:
            video_id = str(documento.get("videoId") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            letra = str(documento.get("lyrics") or "")
            if not letra.strip():
                continue
            canciones.append(
                {
                    "video_id": video_id,
                    "track": documento.get("title") or "",
                    "title": documento.get("title") or "",
                    "artist": documento.get("artist") or "",
                    "language": documento.get("language") or "",
                    "languages": list(documento.get("languages") or []),
                    "lyrics": letra,
                    "backend": documento.get("backend") or "",
                }
            )
        base.client.close()

        with self._lock:
            self.indexer.indexar_canciones(canciones, calcular_embeddings=False)
        print(f"[lirify] loaded {len(canciones)} songs from Atlas", flush=True)
        return len(canciones)

    def reiniciar_indice(self) -> int:
        """Drop the in-memory index and rehydrate terms from Atlas."""
        with self._lock:
            self.indexer.limpiar()
        return self.cargar_desde_atlas()

    # ------------------------------------------------------------------
    # Lecturas
    # ------------------------------------------------------------------
    def estadisticas(self) -> dict[str, Any]:
        with self._lock:
            stats = self.indexer.estadisticas()
        pendientes = sum(
            1 for job in self.jobs.values() if job["status"] in {"queued", "indexing"}
        )
        return {
            **stats,
            "playlist_pending": pendientes,
            "matrix_pending": 0,
            "failed_songs": 0,
            "cached_lyrics": 0,
            "revision": self.revision,
            "serve_only": False,
            "mode": "indexer",
            "autopublish": self.auto_publicar,
            "published_at": self.publicado_en,
            "jobs": sorted(
                (dict(job) for job in self.jobs.values()),
                key=lambda job: job["created_at"],
                reverse=True,
            )[:50],
        }

    def buscar(self, consulta: str, limite: int = 20) -> dict[str, Any]:
        with self._lock:
            return self.indexer.buscar(consulta, limite)

    def recomendar(self, ids: list[str], limite: int = 10) -> dict[str, Any]:
        with self._lock:
            return self.indexer.recomendar(ids, limite)

    def canciones(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "video_id": self.indexer.ids[i],
                    "track": self.indexer.titulos[i],
                    "title": self.indexer.titulos[i],
                    "artist": self.indexer.artistas[i],
                    "language": self.indexer.idiomas[i],
                    "languages": list(self.indexer.idiomas_detectados[i]),
                    "lyrics": self.indexer.letras[i],
                    "backend": self.indexer.backends[i],
                }
                for i in sorted(self.indexer.docs_id)
            ]

    def cancion(self, video_id: str) -> dict[str, Any] | None:
        with self._lock:
            if video_id not in self.indexer.ids:
                return None
            i = self.indexer.ids.index(video_id)
            return {
                "video_id": video_id,
                "track": self.indexer.titulos[i],
                "title": self.indexer.titulos[i],
                "artist": self.indexer.artistas[i],
                "language": self.indexer.idiomas[i],
                "languages": list(self.indexer.idiomas_detectados[i]),
                "lyrics": self.indexer.letras[i],
                "backend": self.indexer.backends[i],
            }

    def matriz_preview(self, tamano: int = 12) -> dict[str, Any]:
        tamano = max(2, min(int(tamano or 12), 64))
        with self._lock:
            ids = sorted(self.indexer.docs_id)[:tamano]
            if not ids:
                return {"ids": [], "matriz": []}
            matriz = self.indexer.construir_matriz_similaridad_coseno()
            recorte = matriz[np.ix_(ids, ids)]
            return {
                "ids": ids,
                "matriz": [[float(valor) for valor in fila] for fila in recorte],
            }
