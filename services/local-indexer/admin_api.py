"""HTTP admin surface for the local dashboard (CRUD + vector reset).

It is mounted only by `local_server.py` (the standalone indexer) and is meant to
stay on the laptop: compose publishes the port on 127.0.0.1 only. Every route is
proxied by go-ui under `/api/db/*`, so the browser never needs a second origin.
"""

from __future__ import annotations

from typing import Any

from db_admin import DbAdmin, DbError
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool


def build_app(pipeline: Any) -> FastAPI:
    app = FastAPI(title="Lirify local database admin", version="1.0.0")
    admin = DbAdmin(pipeline)

    def _run(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except DbError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"{type(exc).__name__}: {exc}"
            ) from exc

    @app.get("/db/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "local-indexer-admin"}

    @app.get("/db/overview")
    def overview() -> dict[str, Any]:
        return _run(admin.overview)

    # -- Mongo songs ----------------------------------------------------
    @app.get("/db/songs")
    def listar_songs(offset: int = 0, limit: int = 50, q: str = "") -> dict[str, Any]:
        return _run(admin.listar_canciones, offset, limit, q)

    @app.get("/db/songs/{video_id}")
    def obtener_song(video_id: str) -> dict[str, Any]:
        return _run(admin.obtener_cancion, video_id)

    @app.post("/db/songs")
    async def crear_song(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return await run_in_threadpool(_run, admin.crear_cancion, payload)

    @app.put("/db/songs/{video_id}")
    async def actualizar_song(video_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return await run_in_threadpool(
            _run, admin.actualizar_cancion, video_id, payload
        )

    @app.delete("/db/songs/{video_id}")
    def eliminar_song(video_id: str) -> dict[str, Any]:
        return _run(admin.eliminar_cancion, video_id)

    # -- query embeddings (same model as indexing) ----------------------
    @app.post("/db/embed")
    async def embed(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return await run_in_threadpool(
            _run, admin.embeber_textos, payload.get("texts") or []
        )

    @app.post("/db/search")
    async def search(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return await run_in_threadpool(
            _run,
            admin.buscar_semantico,
            payload.get("query") or "",
            payload.get("limit") or 20,
        )

    # -- Qdrant vectors -------------------------------------------------
    @app.get("/db/vectors")
    def listar_vectors(limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        return _run(admin.listar_vectores, limit, cursor)

    @app.post("/db/vectors/{video_id}/embed")
    def reembeber(video_id: str) -> dict[str, Any]:
        return _run(admin.reembeber, video_id)

    @app.delete("/db/vectors/{video_id}")
    def eliminar_vector(video_id: str) -> dict[str, Any]:
        return _run(admin.eliminar_vector, video_id)

    @app.post("/db/vectors/rebuild")
    def reconstruir() -> dict[str, Any]:
        return _run(admin.reconstruir_vectores)

    @app.post("/db/vectors/reset")
    def resetear() -> dict[str, Any]:
        return _run(admin.resetear_vectores)

    @app.post("/db/index/reload")
    def recargar() -> dict[str, Any]:
        return _run(admin.reiniciar_indice)

    return app
