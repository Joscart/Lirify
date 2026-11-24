"""gRPC surface (HTTP/2, h2c) for python-backend.

Cloud Run terminates TLS and forwards h2c to the container, so this server binds
plain HTTP/2 on ``GRPC_PORT`` (50051) behind the small Caddy mux described in
``Caddyfile`` / ``run.sh``. That keeps one Cloud Run service serving both the
gRPC web-UI channels and the HTTP/JSON bot API.

The servicer is a thin adapter: every rule (filters, ranking, jobs, stashes)
stays in ``main.py`` so REST and gRPC cannot drift apart.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import time
from typing import Any, Dict, List

import grpc
from grpc import aio as grpc_aio

import main as core
import player_api
from lirifypb import lirify_pb2 as pb
from lirifypb import lirify_pb2_grpc as pb_grpc
from vector import EMBEDDING_PROVIDER, get_vector_store

VECTORS = get_vector_store()
MAX_MESSAGE = 16 * 1024 * 1024
_RETRY_TASK: "asyncio.Task[None] | None" = None


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def _track(
    song: Dict[str, Any], include_lyrics: bool = False
) -> pb.Track:
    video_id = song.get("video_id", "")
    duration = 0.0
    try:
        duration = float(player_api.DURATIONS.get(video_id) or core.DURATIONS.get(video_id) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    lyrics = song.get("lyrics") or ""
    return pb.Track(
        video_id=video_id,
        title=song.get("track") or song.get("title", ""),
        artist=song.get("artist", ""),
        language=song.get("language", ""),
        backend=song.get("backend") or "",
        youtube_title=song.get("title", ""),
        duration=duration,
        lyrics=lyrics if include_lyrics else "",
        synced=bool(re.search(r"\[\d{1,2}:\d{2}", lyrics)),
        thumb=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "",
        stream_url=f"/api/player/proxy/{video_id}?kind=audio" if video_id else "",
    )


def _summary(song: Dict[str, Any], score: float) -> pb.TrackSummary:
    video_id = song.get("video_id", "")
    return pb.TrackSummary(
        video_id=video_id,
        title=song.get("track") or song.get("title", ""),
        artist=song.get("artist", ""),
        language=song.get("language", ""),
        score=float(score or 0.0),
        thumb=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "",
        duration=float(player_api.DURATIONS.get(video_id) or 0),
    )


def _job(job: Dict[str, Any]) -> pb.Job:
    return pb.Job(
        job_id=str(job.get("job_id") or ""),
        action=str(job.get("action") or ""),
        url=str(job.get("url") or ""),
        status=str(job.get("status") or ""),
        stage=str(job.get("stage") or ""),
        error=str(job.get("error") or ""),
        added=int(job.get("added") or 0),
        attempts=int(job.get("attempts") or 0),
        source=str(job.get("source") or ""),
        created_at=int(float(job.get("created_at") or 0)),
        updated_at=int(float(job.get("updated_at") or job.get("created_at") or 0)),
    )


def _stats_payload() -> Dict[str, Any]:
    return core.stats()


def _find_song(video_id: str) -> Dict[str, Any] | None:
    for song in core.STATE.get("songs") or []:
        if song.get("video_id") == video_id:
            return song
    return None



async def _abort(context: Any, code: "grpc.StatusCode", message: str) -> None:
    """Abort an RPC after flushing initial metadata.

    Caddy's HTTP/2 upstream handling drops "trailers-only" gRPC error responses
    (grpc-status in the initial HEADERS frame), which surfaces to clients as
    UNKNOWN. Sending metadata first forces a normal response + trailers, so real
    status codes survive the h2c mux.
    """
    try:
        await context.send_initial_metadata((("x-lirify", "python-backend"),))
    except Exception:
        pass
    await context.abort(code, message)


async def _reject_on_serving(context: Any) -> bool:
    """Return True (after aborting) when this is a read-only serving replica."""
    if not core.SERVE_ONLY:
        return False
    await _abort(context, grpc.StatusCode.UNIMPLEMENTED, core.READ_ONLY_DETAIL)
    return True


# ---------------------------------------------------------------------------
# Servicer
# ---------------------------------------------------------------------------


class LirifyServicer(pb_grpc.LirifyServiceServicer):
    # -- player ---------------------------------------------------------
    async def Search(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        query = request.query or ""
        limit = request.limit or 20
        payload = await asyncio.to_thread(core.search, query, limit)
        return pb.SearchResponse(
            query=payload.get("query", query),
            results=[
                pb.TrackSummary(
                    video_id=row.get("video_id", ""),
                    title=row.get("title", ""),
                    artist=row.get("artist", ""),
                    language=row.get("language", ""),
                    score=float(row.get("score") or 0),
                    thumb=f"https://i.ytimg.com/vi/{row.get('video_id','')}/hqdefault.jpg",
                    duration=float(player_api.DURATIONS.get(row.get("video_id", "")) or 0),
                )
                for row in payload.get("results", [])
            ],
        )

    async def Recommend(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        seeds = [request.video_id] if request.video_id else []
        seeds += [s for s in request.seed_video_ids if s]
        payload = await asyncio.to_thread(
            core.recommend_songs, seeds, request.limit or 10
        )
        by_id = {s["video_id"]: s for s in core.STATE.get("songs") or []}
        results = []
        for row in payload.get("recommendations", []):
            song = by_id.get(row["video_id"])
            if song is not None:
                results.append(_summary(song, row.get("score", 0)))
            else:
                results.append(pb.TrackSummary(**row))
        return pb.RecommendResponse(
            seed_video_id=payload.get("seed_video_id", ""),
            recommendations=results,
            engine=payload.get("engine", "none"),
        )

    async def GetTrack(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        song = _find_song(request.video_id)
        if song is None:
            await _abort(context, grpc.StatusCode.NOT_FOUND, "Unknown video id")
        return pb.GetTrackResponse(track=_track(song, request.include_lyrics))

    async def ListTracks(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        songs: List[Dict[str, Any]] = core.STATE.get("songs") or []
        language = (request.language or "").strip()
        if language:
            songs = [s for s in songs if s.get("language") == language]
        offset = max(0, int(request.offset or 0))
        limit = int(request.limit or 60)
        limit = max(1, min(limit, 200))
        slice_ = songs[offset : offset + limit]
        return pb.ListTracksResponse(
            total=len(songs), tracks=[_track(s) for s in slice_]
        )

    async def GetLyrics(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        song = _find_song(request.video_id)
        if song is None:
            await _abort(context, grpc.StatusCode.NOT_FOUND, "Unknown video id")
        parsed = await asyncio.to_thread(player_api.lyrics_for, song)
        lines = [
            pb.LyricsLine(
                time_ms=int(round(float(line.get("t") or 0) * 1000)),
                text=line.get("text", ""),
            )
            for line in parsed.get("lines", [])
        ]
        return pb.GetLyricsResponse(
            video_id=request.video_id,
            synced=bool(parsed.get("synced")),
            lines=lines,
            raw=song.get("lyrics", ""),
            language=song.get("language", ""),
        )

    async def Stream(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        song = _find_song(request.video_id)
        if song is None:
            await _abort(context, grpc.StatusCode.NOT_FOUND, "Unknown video id")
        duration = float(player_api.DURATIONS.get(request.video_id) or 0)
        return pb.StreamResponse(
            video_id=request.video_id,
            url=f"/api/player/proxy/{request.video_id}?kind=audio",
            duration=duration,
            expires_at=int(time.time()) + player_api.STREAM_TTL,
        )

    # -- indexing -------------------------------------------------------
    async def IndexPlaylist(self, request, context):  # noqa: N802
        if await _reject_on_serving(context):
            return pb.Job()
        from bot_api import validate_playlist_url
        from fastapi import HTTPException

        if not (request.playlist_url or "").strip():
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, "playlist_url is required")
            return pb.Job()
        try:
            url = validate_playlist_url(request.playlist_url)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else exc.detail.get("message", "")
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, detail)
            return pb.Job()
        job_id = await core.enqueue_playlist(
            url, request.limit or None, request.source or "go-webui"
        )
        job = core.job_snapshot(job_id) or {"job_id": job_id, "status": "queued"}
        return _job(job)

    async def QueuePlaylists(self, request, context):  # noqa: N802
        if await _reject_on_serving(context):
            return pb.QueuePlaylistsResponse()
        from bot_api import validate_playlist_url
        from fastapi import HTTPException

        jobs = []
        for raw in request.playlist_urls:
            if not (raw or "").strip():
                continue
            try:
                url = validate_playlist_url(raw)
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else exc.detail.get("message", "")
                await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, detail)
                return pb.QueuePlaylistsResponse()
            job_id = await core.enqueue_playlist(
                url, request.limit or None, request.source or "go-webui"
            )
            jobs.append(core.job_snapshot(job_id) or {"job_id": job_id, "status": "queued"})
        return pb.QueuePlaylistsResponse(
            jobs=[_job(j) for j in jobs], queue_size=core.PLAYLIST_QUEUE.qsize()
        )

    async def GetJob(self, request, context):  # noqa: N802
        job = await asyncio.to_thread(core.job_snapshot, request.job_id)
        if not job:
            await _abort(context, grpc.StatusCode.NOT_FOUND, "Unknown job id")
        return pb.GetJobResponse(job=_job(job))

    async def ExtractVideoIds(self, request, context):  # noqa: N802
        if await _reject_on_serving(context):
            return pb.ExtractVideoIdsResponse()
        url = (request.playlist_url or "").strip()
        if not url:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, "playlist_url is required")
            return pb.ExtractVideoIdsResponse()
        try:
            ids = await asyncio.to_thread(core.extract_video_ids, url)
        except Exception as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return pb.ExtractVideoIdsResponse()
        if request.limit:
            ids = ids[: request.limit]
        return pb.ExtractVideoIdsResponse(count=len(ids), video_ids=ids)

    async def GetIndexStats(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        return await self._stats_message()

    async def WatchIndexStats(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        interval = max(2, min(int(request.interval_seconds or 5), 60))
        while True:
            # aio ServicerContext exposes cancelled(), not is_active().
            if context.cancelled():
                return
            yield await self._stats_message()
            await asyncio.sleep(interval)

    async def _stats_message(self) -> pb.IndexStats:
        payload = await asyncio.to_thread(_stats_payload)
        queue = payload.get("queue") or {}
        recent = await asyncio.to_thread(core.STORE.jobs_recent, 25)
        storage = payload.get("storage") or {}
        # Present only in the local-indexer image; the serving image has no
        # local_store module and reports zeros.
        local_vocab = local_terms = 0
        local_dir = ""
        try:
            import local_store

            info = await asyncio.to_thread(local_store.info)
            local_vocab = int(info.get("vocabulary_terms") or 0)
            local_terms = int(info.get("inverted_terms") or 0)
            local_dir = str(info.get("directory") or "")
        except Exception:
            pass
        return pb.IndexStats(
            indexed_songs=int(payload.get("indexed_songs") or 0),
            video_ids=int(payload.get("video_ids") or 0),
            vocabulary_size=int(payload.get("vocabulary_size") or 0),
            inverted_terms=int(payload.get("inverted_terms") or 0),
            lyrics_tokens=int(payload.get("lyrics_tokens") or 0),
            languages={k: int(v) for k, v in (payload.get("languages") or {}).items()},
            backends={k: int(v) for k, v in (payload.get("backends") or {}).items()},
            playlist_pending=int(queue.get("playlist_pending") or 0),
            matrix_pending=int(queue.get("matrix_pending") or 0),
            failed_songs=int(queue.get("failed_songs") or 0),
            cached_lyrics=int(queue.get("cached_lyrics") or 0),
            jobs=[_job(j) for j in recent],
            matrices_available=list(payload.get("matrices_available") or []),
            weights={k: float(v) for k, v in (payload.get("weights") or {}).items()},
            generated_at=int(time.time()),
            lyrics_providers=list(payload.get("lyrics_providers") or []),
            top_terms=list(payload.get("top_terms") or []),
            stateless=bool(storage.get("stateless")),
            tracks_store=str(storage.get("tracks") or ""),
            vectors_store=str(storage.get("vectors") or ""),
            max_indexed_songs=int(storage.get("max_indexed_songs") or 0),
            serve_only=core.SERVE_ONLY,
            mode="serve-only" if core.SERVE_ONLY else "indexer",
            embedding_provider=EMBEDDING_PROVIDER,
            tokenizer=core.qwen_tokenizer.TOKENIZER_ID if core.qwen_tokenizer.available() else "legacy",
            jaccard_scope=str(payload.get("jaccard_scope") or core.JACCARD_SCOPE),
            local_vocabulary_terms=local_vocab,
            local_inverted_terms=local_terms,
            local_index_dir=local_dir,
        )

    async def GetFailedSongs(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        failed = await asyncio.to_thread(core.STORE.failed_all)
        cached = await asyncio.to_thread(core.STORE.cached_lyric_count)
        limit = max(1, min(int(request.limit or 100), 500))
        rows = sorted(
            failed.values(), key=lambda row: float(row.get("last_try") or 0), reverse=True
        )[:limit]
        return pb.GetFailedSongsResponse(
            total=len(failed),
            cached_lyrics=int(cached),
            max_attempts=core.MAX_ATTEMPTS,
            retry_interval_seconds=core.RETRY_INTERVAL,
            failed=[
                pb.FailedSong(
                    video_id=row.get("video_id", ""),
                    title=row.get("title", ""),
                    artist=row.get("artist", ""),
                    reason=row.get("reason", ""),
                    attempts=int(row.get("attempts") or 0),
                    last_try=int(float(row.get("last_try") or 0)),
                    duration=float(row.get("duration") or 0),
                )
                for row in rows
            ],
        )

    async def RetryFailed(self, request, context):  # noqa: N802
        if await _reject_on_serving(context):
            return pb.RetryFailedResponse()
        global _RETRY_TASK
        if _RETRY_TASK is not None and not _RETRY_TASK.done():
            return pb.RetryFailedResponse(
                started=False, already_running=True, message="A retry pass is already running"
            )

        async def _run() -> None:
            try:
                await core.retry_failed_songs()
            except Exception as exc:  # pragma: no cover
                print(f"[lirify] retry pass failed: {exc}", flush=True)

        _RETRY_TASK = asyncio.create_task(_run())
        return pb.RetryFailedResponse(
            started=True,
            already_running=False,
            message="Retry pass started; watch the progress stream for results",
        )

    async def MatrixPreview(self, request, context):  # noqa: N802
        # gRPC bypasses the FastAPI middleware; refresh from the shared store too.
        await core.ensure_fresh_index()
        payload = await asyncio.to_thread(
            player_api.preview_matrices, core.STATE, int(request.size or 12)
        )
        if payload is None:
            await _abort(context, grpc.StatusCode.NOT_FOUND, "Nothing indexed yet")
        matrices = {
            name: pb.MatrixPreview(
                shape=[int(value) for value in (matrix.get("shape") or [])],
                rows=[pb.MatrixPreviewRow(values=row) for row in (matrix.get("values") or [])],
            )
            for name, matrix in (payload.get("matrices") or {}).items()
        }
        return pb.MatrixPreviewResponse(
            shape=[int(value) for value in (payload.get("shape") or [])],
            size=int(payload.get("size") or 0),
            songs=[
                pb.TrackSummary(
                    video_id=row.get("video_id", ""),
                    title=row.get("title", ""),
                    artist=row.get("artist", ""),
                    language=row.get("language", ""),
                )
                for row in (payload.get("songs") or [])
            ],
            matrices=matrices,
            weights={k: float(v) for k, v in (payload.get("weights") or {}).items()},
        )

    # -- bot ------------------------------------------------------------
    async def IndexPlaylistFromBot(self, request, context):  # noqa: N802
        if await _reject_on_serving(context):
            return pb.IndexPlaylistFromBotResponse()
        from bot_api import validate_playlist_url
        from fastapi import HTTPException

        try:
            url = validate_playlist_url(request.playlist_url)
        except HTTPException as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc.detail))
            return pb.IndexPlaylistFromBotResponse()
        key = (request.idempotency_key or "").strip()
        existing = await asyncio.to_thread(core.STORE.idempotent_job, key) if key else None
        if existing:
            job = await asyncio.to_thread(core.job_snapshot, existing)
            if job:
                return pb.IndexPlaylistFromBotResponse(
                    accepted=job.get("status") not in ("error", "skipped"),
                    job=_job(job),
                    job_status_url=f"/api/v1/bot/jobs/{existing}",
                )
        job_id = await core.enqueue_playlist(
            url, request.limit or None, f"bot:{request.source_bot or 'unknown'}"[:120]
        )
        if key:
            await asyncio.to_thread(core.STORE.remember_idempotent_job, key, job_id)
        job = await asyncio.to_thread(core.job_snapshot, job_id)
        return pb.IndexPlaylistFromBotResponse(
            accepted=True,
            job=_job(job or {"job_id": job_id, "status": "queued"}),
            job_status_url=f"/api/v1/bot/jobs/{job_id}",
        )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def _install_optional_services(server: grpc_aio.Server) -> None:
    try:  # reflection makes grpcurl usable against a private revision
        from grpc_reflection.v1alpha import reflection

        service_names = [
            pb.DESCRIPTOR.services_by_name["LirifyService"].full_name,
            reflection.SERVICE_NAME,
        ]
        reflection.enable_server_reflection(service_names, server)
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"[lirify] gRPC reflection disabled: {exc}", flush=True)


async def start_server(port: int | None = None) -> "grpc_aio.Server":
    """Create and start the gRPC server on the current event loop.

    Called from the FastAPI startup hook so the REST and gRPC surfaces share one
    process — and therefore one copy of the in-memory index. Running
    ``python -m grpc_server`` as a second process doubles RSS (each process
    imports ``main`` and rebuilds STATE), which cannot fit in a 512 MiB Cloud Run
    container.
    """
    port = port or int(os.environ.get("GRPC_PORT", "50051"))
    server = grpc_aio.server(
        options=[
            ("grpc.max_receive_message_length", MAX_MESSAGE),
            ("grpc.max_send_message_length", MAX_MESSAGE),
            ("grpc.keepalive_time_ms", 60_000),
        ]
    )
    pb_grpc.add_LirifyServiceServicer_to_server(LirifyServicer(), server)
    _install_optional_services(server)

    try:
        from grpc_health.v1 import health, health_pb2, health_pb2_grpc

        health_service = health.aio.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_service, server)
        await health_service.set("lirify.v1.LirifyService", health_pb2.HealthCheckResponse.SERVING)
        await health_service.set("", health_pb2.HealthCheckResponse.SERVING)
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"[lirify] gRPC health service disabled: {exc}", flush=True)

    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    print(f"[lirify] gRPC (h2c) listening on :{port} (in-process)", flush=True)
    return server


async def stop_server(server: "grpc_aio.Server | None") -> None:
    if server is None:
        return
    await server.stop(grace=5)


async def serve() -> None:
    """Standalone gRPC server, for local development and tests."""
    server = await start_server()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - not main thread
            pass
    await stop.wait()
    await stop_server(server)


def main_entry() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main_entry()
