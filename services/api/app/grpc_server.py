"""gRPC adapter for the read-only cloud replica.

Every read RPC is answered from committed songs + pre-computed LLM embeddings.
Every indexing RPC answers UNIMPLEMENTED: indexing lives in `local-indexer`.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import grpc
import main as core
import player_api
from grpc import aio as grpc_aio
from lirifypb import lirify_pb2 as pb
from lirifypb import lirify_pb2_grpc as pb_grpc

MAX_MESSAGE = 16 * 1024 * 1024


def _thumb(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _track(song: dict[str, Any], incluir_letra: bool = False) -> Any:
    video_id = str(song.get("video_id") or "")
    return pb.Track(
        video_id=video_id,
        title=str(song.get("track") or song.get("title") or ""),
        artist=str(song.get("artist") or ""),
        language=str(song.get("language") or ""),
        backend=str(song.get("backend") or ""),
        youtube_title=str(song.get("title") or ""),
        duration=float(core.DURATIONS.get(video_id) or song.get("duration") or 0),
        lyrics=str(song.get("lyrics") or "") if incluir_letra else "",
        synced=False,
        thumb=_thumb(video_id),
        stream_url="",
    )


def _summary(row: dict[str, Any]) -> Any:
    video_id = str(row.get("video_id") or "")
    return pb.TrackSummary(
        video_id=video_id,
        title=str(row.get("title") or ""),
        artist=str(row.get("artist") or ""),
        language=str(row.get("language") or ""),
        score=round(float(row.get("score") or 0), 6),
        thumb=_thumb(video_id),
        duration=float(core.DURATIONS.get(video_id) or 0),
    )


def _stats() -> Any:
    payload = core.stats_payload()
    return pb.IndexStats(
        indexed_songs=int(payload.get("indexed_songs") or 0),
        video_ids=int(payload.get("video_ids") or 0),
        vocabulary_size=0,
        inverted_terms=0,
        lyrics_tokens=0,
        languages=payload.get("languages") or {},
        backends=payload.get("backends") or {},
        playlist_pending=0,
        matrix_pending=0,
        failed_songs=0,
        cached_lyrics=0,
        jobs=[],
        matrices_available=[],
        weights=core.WEIGHTS,
        generated_at=int(time.time()),
        lyrics_providers=[],
        top_terms=[],
        stateless=True,
        tracks_store=str(payload.get("tracks_store") or ""),
        vectors_store=str(payload.get("vectors_store") or ""),
        max_indexed_songs=int(payload.get("max_indexed_songs") or 0),
        serve_only=True,
        mode="serve-only",
        embedding_provider="precomputed",
        tokenizer="",
        jaccard_scope=core.JACCARD_SCOPE,
        local_vocabulary_terms=0,
        local_inverted_terms=0,
        local_index_dir="",
        revision=int(payload.get("revision") or 0),
    )


def _find(video_id: str) -> dict[str, Any] | None:
    return core.STATE["by_id"].get(video_id)


async def _abort(context: Any, code: grpc.StatusCode, message: str) -> None:
    await context.abort(code, message)


async def _reject_indexing(context: Any) -> None:
    await _abort(context, grpc.StatusCode.UNIMPLEMENTED, core.READ_ONLY_DETAIL)


class LirifyServicer(pb_grpc.LirifyServiceServicer):
    async def Search(self, request, context):
        payload = await asyncio.to_thread(
            core.search, request.query or "", request.limit or 20
        )
        return pb.SearchResponse(
            query=payload.get("query", request.query or ""),
            results=[_summary(row) for row in payload.get("results") or []],
        )

    async def Recommend(self, request, context):
        seeds = [request.video_id] if request.video_id else []
        seeds += [seed for seed in request.seed_video_ids if seed]
        payload = await asyncio.to_thread(
            core.recommend_songs, seeds, request.limit or 10
        )
        return pb.RecommendResponse(
            seed_video_id=payload.get("seed_video_id", ""),
            recommendations=[
                _summary(row) for row in payload.get("recommendations") or []
            ],
            engine=payload.get("engine", "none"),
            weights=core.WEIGHTS,
        )

    async def GetTrack(self, request, context):
        await asyncio.to_thread(core.ensure_fresh_index)
        song = _find(request.video_id)
        if song is None:
            await _abort(context, grpc.StatusCode.NOT_FOUND, "Unknown video id")
        return pb.GetTrackResponse(track=_track(song, request.include_lyrics))

    async def ListTracks(self, request, context):
        await asyncio.to_thread(core.ensure_fresh_index)
        songs = list(core.STATE["songs"])
        if request.language:
            songs = [song for song in songs if song["language"] == request.language]
        offset = max(0, int(request.offset or 0))
        limit = max(1, min(int(request.limit or 60), 200))
        return pb.ListTracksResponse(
            total=len(songs),
            tracks=[_track(song) for song in songs[offset : offset + limit]],
        )

    async def GetLyrics(self, request, context):
        song = _find(request.video_id)
        if song is None:
            await _abort(context, grpc.StatusCode.NOT_FOUND, "Unknown video id")
        parsed = await asyncio.to_thread(player_api.lyrics_for, song)
        return pb.GetLyricsResponse(
            video_id=request.video_id,
            synced=bool(parsed.get("synced")),
            lines=[
                pb.LyricsLine(
                    time_ms=round(float(line.get("t") or 0) * 1000),
                    text=line.get("text", ""),
                )
                for line in parsed.get("lines") or []
            ],
            raw=str(song.get("lyrics") or ""),
            language=str(song.get("language") or ""),
        )

    async def Stream(self, request, context):
        song = _find(request.video_id)
        if song is None:
            await _abort(context, grpc.StatusCode.NOT_FOUND, "Unknown video id")
        return pb.StreamResponse(
            video_id=request.video_id,
            url=f"/api/player/proxy/{request.video_id}?kind=audio",
            duration=float(core.DURATIONS.get(request.video_id) or 0),
            expires_at=int(time.time()) + player_api.STREAM_TTL,
        )

    async def GetIndexStats(self, request, context):
        return _stats()

    async def WatchIndexStats(self, request, context):
        interval = max(2, min(int(request.interval_seconds or 5), 60))
        while True:
            yield _stats()
            await asyncio.sleep(interval)

    async def GetFailedSongs(self, request, context):
        return pb.GetFailedSongsResponse(
            total=0, cached_lyrics=0, max_attempts=0, retry_interval_seconds=0
        )

    async def MatrixPreview(self, request, context):
        return pb.MatrixPreviewResponse(shape=[0, 0], size=0)

    async def IndexPlaylist(self, request, context):
        await _reject_indexing(context)

    async def QueuePlaylists(self, request, context):
        await _reject_indexing(context)

    async def GetJob(self, request, context):
        await _abort(context, grpc.StatusCode.NOT_FOUND, "Unknown job id")

    async def ExtractVideoIds(self, request, context):
        await _reject_indexing(context)

    async def RetryFailed(self, request, context):
        await _reject_indexing(context)

    async def IndexPlaylistFromBot(self, request, context):
        await _reject_indexing(context)


async def start_server(port: int | None = None) -> grpc_aio.Server:
    port = port or int(os.environ.get("GRPC_PORT", "50051"))
    server = grpc_aio.server(
        options=[
            ("grpc.max_receive_message_length", MAX_MESSAGE),
            ("grpc.max_send_message_length", MAX_MESSAGE),
        ]
    )
    pb_grpc.add_LirifyServiceServicer_to_server(LirifyServicer(), server)
    try:
        from grpc_reflection.v1alpha import reflection

        reflection.enable_server_reflection(
            [
                pb.DESCRIPTOR.services_by_name["LirifyService"].full_name,
                reflection.SERVICE_NAME,
            ],
            server,
        )
    except Exception as exc:  # noqa: BLE001 - optional dependency
        print(f"[lirify] gRPC reflection disabled: {exc}", flush=True)
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    print(f"[lirify] gRPC serving on :{port} (read-only)", flush=True)
    return server


async def stop_server(server: grpc_aio.Server | None) -> None:
    if server is not None:
        await server.stop(grace=5)


async def serve() -> None:
    import signal

    server = await start_server()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    await stop.wait()
    await stop_server(server)


def main_entry() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main_entry()
