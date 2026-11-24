"""Laptop indexer backend: the full pipeline, over gRPC, with no HTTP UI.

This process is the *writer* half of Lirify. It reuses ``main.py`` (the same
scrape -> language filter -> dedupe -> matrix pipeline) and ``grpc_server.py``
(the same ``LirifyService`` adapters), but:

* ``SERVE_ONLY=0`` so the indexing RPCs and workers are live;
* the workers start from this entrypoint instead of FastAPI's startup hook;
* it registers the extra ``LirifyIndexerService`` for publishing to Atlas/Qdrant
  and for the local Qwen3 vocabulary/inverted-index files;
* it embeds through llama.cpp (``LLAMA_EMBED_URL``) rather than the hash trick.

The local dashboard never talks to this process's internals: every action is a
gRPC call, which is why local-ui can stay a thin, stateless Go adapter.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from typing import Any, Dict

# Must be set before importing main: this process is the indexer, and it must not
# open a second nested gRPC listener from main.start_workers(). Forcing the role
# (rather than setdefault) makes the entrypoint self-consistent even if a shared
# .env still says SERVE_ONLY=true.
os.environ["SERVE_ONLY"] = "0"
os.environ["GRPC_INPROCESS"] = "0"

import grpc  # noqa: E402
from grpc import aio as grpc_aio  # noqa: E402

import main as core  # noqa: E402
import local_store  # noqa: E402
from grpc_server import LirifyServicer, MAX_MESSAGE  # noqa: E402
from lirifypb import lirify_pb2 as pb  # noqa: E402
from lirifypb import lirify_pb2_grpc as pb_grpc  # noqa: E402

# Every successful commit rewrites the two local artefacts (vocabulary + full
# inverted index) through the Qwen3 tokenizer. The cloud serving stack never
# registers this hook.
core.register_commit_hook(local_store.rebuild)


class LocalIndexerServicer(pb_grpc.LirifyIndexerServiceServicer):
    """Publish + local-index introspection, the only laptop-only RPCs."""

    async def PublishToCloud(self, request, context):  # noqa: N802
        songs = list(core.STATE.get("songs") or [])
        if not songs:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Nothing indexed yet: index a playlist before publishing",
            )
        limit = int(request.limit or 0)
        selected = songs[:limit] if limit > 0 else songs
        try:
            await asyncio.to_thread(core.persist, selected)
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, f"publish failed: {exc}")

        stats: Dict[str, Any] = {"vocabulary_terms": 0, "inverted_terms": 0, "directory": ""}
        try:
            if request.rebuild_local_index or not os.path.exists(local_store.paths()[0]):
                stats = await asyncio.to_thread(local_store.rebuild, songs)
            else:
                stats = await asyncio.to_thread(local_store.info)
        except Exception as exc:
            print(f"[lirify] local index rebuild failed: {exc}", flush=True)

        vectors = len(selected) if core.VECTORS.backend != "none" else 0
        return pb.PublishToCloudResponse(
            published=True,
            songs=len(selected),
            vectors=vectors,
            vocabulary_terms=int(stats.get("vocabulary_terms") or 0),
            inverted_terms=int(stats.get("inverted_terms") or 0),
            directory=str(stats.get("directory") or ""),
            message=(
                f"Published {len(selected)} songs to {core.STORE.backend} and "
                f"{core.VECTORS.backend}; local index rebuilt with "
                f"{stats.get('vocabulary_terms', 0)} terms"
            ),
            published_at=int(time.time()),
        )

    async def GetLocalIndex(self, request, context):  # noqa: N802
        try:
            payload = await asyncio.to_thread(local_store.info)
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, f"local index unavailable: {exc}")
        return pb.GetLocalIndexResponse(
            info=pb.LocalIndexInfo(
                directory=str(payload.get("directory") or ""),
                tokenizer=str(payload.get("tokenizer") or ""),
                tokenizer_backend=str(payload.get("tokenizer_backend") or ""),
                embedding_provider=str(payload.get("embedding_provider") or ""),
                documents=int(payload.get("documents") or 0),
                vocabulary_terms=int(payload.get("vocabulary_terms") or 0),
                inverted_terms=int(payload.get("inverted_terms") or 0),
                vocabulary_bytes=int(payload.get("vocabulary_bytes") or 0),
                inverted_index_bytes=int(payload.get("inverted_index_bytes") or 0),
                updated_at=int(payload.get("updated_at") or 0),
                vocabulary_path=str(payload.get("vocabulary_path") or ""),
                inverted_index_path=str(payload.get("inverted_index_path") or ""),
            )
        )


def _install_reflection(server: grpc_aio.Server) -> None:
    try:
        from grpc_reflection.v1alpha import reflection

        names = [
            pb.DESCRIPTOR.services_by_name["LirifyService"].full_name,
            pb.DESCRIPTOR.services_by_name["LirifyIndexerService"].full_name,
            reflection.SERVICE_NAME,
        ]
        reflection.enable_server_reflection(names, server)
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"[lirify] gRPC reflection disabled: {exc}", flush=True)


async def start_local_server(port: int | None = None) -> grpc_aio.Server:
    port = port or int(os.environ.get("GRPC_PORT", "50051"))
    server = grpc_aio.server(
        options=[
            ("grpc.max_receive_message_length", MAX_MESSAGE),
            ("grpc.max_send_message_length", MAX_MESSAGE),
            ("grpc.keepalive_time_ms", 60_000),
        ]
    )
    pb_grpc.add_LirifyServiceServicer_to_server(LirifyServicer(), server)
    pb_grpc.add_LirifyIndexerServiceServicer_to_server(LocalIndexerServicer(), server)
    _install_reflection(server)
    try:
        from grpc_health.v1 import health, health_pb2, health_pb2_grpc

        health_service = health.aio.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_service, server)
        await health_service.set("lirify.v1.LirifyService", health_pb2.HealthCheckResponse.SERVING)
        await health_service.set(
            "lirify.v1.LirifyIndexerService", health_pb2.HealthCheckResponse.SERVING
        )
        await health_service.set("", health_pb2.HealthCheckResponse.SERVING)
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"[lirify] gRPC health service disabled: {exc}", flush=True)
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    print(
        f"[lirify] local-indexer gRPC listening on :{port} "
        f"(serve_only={core.SERVE_ONLY}, embeddings={core.EMBEDDING_PROVIDER})",
        flush=True,
    )
    return server


async def serve() -> None:
    server = await start_local_server()
    # Start scraping/matrix/retry workers exactly like the FastAPI startup hook
    # would, but in this process. recover_queue() runs inside it.
    try:
        await core.start_workers()
    except Exception as exc:  # pragma: no cover - Atlas hiccup
        print(f"[lirify] worker bootstrap failed: {exc}", flush=True)

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover
            pass
    await stop.wait()

    for task in core.WORKERS:
        task.cancel()
    core.WORKERS.clear()
    await server.stop(grace=5)


def main_entry() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main_entry()
