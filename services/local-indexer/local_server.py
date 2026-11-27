"""Standalone gRPC server for the local indexer.

The process owns ingestion, the index, the LLM embeddings and the cloud writes.
It never calls the cloud API, and the cloud API never calls it. Its only client
is the local dashboard (go-ui in DASHBOARD_MODE=local).
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from typing import Any

import admin_api
import grpc
import ingest
import uvicorn
from grpc import aio as grpc_aio
from lirifypb import lirify_pb2 as pb
from lirifypb import lirify_pb2_grpc as pb_grpc
from lyrics_sources import PROVIDERS
from pipeline import Pipeline

MAX_MESSAGE = 16 * 1024 * 1024
PIPELINE = Pipeline()


def _thumb(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _job(job: dict[str, Any]) -> Any:
    return pb.Job(
        job_id=str(job.get("job_id") or ""),
        action=str(job.get("action") or "index"),
        url=str(job.get("url") or ""),
        status=str(job.get("status") or ""),
        stage=str(job.get("stage") or ""),
        error=str(job.get("error") or ""),
        added=int(job.get("added") or 0),
        attempts=int(job.get("attempts") or 0),
        source=str(job.get("source") or ""),
        created_at=int(job.get("created_at") or 0),
        updated_at=int(job.get("updated_at") or 0),
        error_code=str(job.get("error_code") or ""),
        retry_mode=str(job.get("retry_mode") or ""),
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
        duration=0.0,
    )


def _track(song: dict[str, Any], incluir_letra: bool = False) -> Any:
    video_id = str(song.get("video_id") or "")
    letra = str(song.get("lyrics") or "")
    return pb.Track(
        video_id=video_id,
        title=str(song.get("track") or song.get("title") or ""),
        artist=str(song.get("artist") or ""),
        language=str(song.get("language") or ""),
        backend=str(song.get("backend") or ""),
        youtube_title=str(song.get("title") or ""),
        duration=0.0,
        lyrics=letra if incluir_letra else "",
        synced=False,
        thumb=_thumb(video_id),
        stream_url="",
    )


def _stats() -> Any:
    datos = PIPELINE.estadisticas()
    return pb.IndexStats(
        indexed_songs=int(datos.get("songs_indexed") or 0),
        video_ids=int(datos.get("video_ids") or 0),
        vocabulary_size=int(datos.get("vocabulary_size") or 0),
        inverted_terms=int(datos.get("inverted_terms") or 0),
        lyrics_tokens=int(datos.get("lyrics_tokens") or 0),
        languages=datos.get("languages") or {},
        backends=datos.get("backends") or {},
        playlist_pending=int(datos.get("playlist_pending") or 0),
        matrix_pending=0,
        failed_songs=0,
        cached_lyrics=0,
        jobs=[_job(job) for job in datos.get("jobs") or []],
        matrices_available=["unified", "lyrics", "name", "artist"],
        weights={"name": 0.10, "artist": 0.05, "lyrics": 0.85},
        generated_at=int(time.time()),
        lyrics_providers=sorted(name for name, _ in PROVIDERS),
        top_terms=list(PIPELINE.indexer.vocabulary)[:20],
        stateless=False,
        tracks_store="memory+atlas",
        vectors_store="qdrant" if os.environ.get("QDRANT_URL") else "none",
        max_indexed_songs=-1,
        serve_only=False,
        mode="indexer",
        embedding_provider=str(
            datos.get("embedding_provider") or "sentence-transformers"
        ),
        tokenizer=str(datos.get("embedding_model") or ""),
        jaccard_scope="name+artist",
        local_vocabulary_terms=int(datos.get("vocabulary_size") or 0),
        local_inverted_terms=int(datos.get("inverted_terms") or 0),
        local_index_dir=(os.environ.get("LOCAL_INDEX_DIR") or "").strip(),
        revision=int(datos.get("revision") or 0),
    )


class LocalServicer(pb_grpc.LirifyServiceServicer):
    async def Search(self, request, context):
        payload = await asyncio.to_thread(
            PIPELINE.buscar, request.query or "", request.limit or 20
        )
        return pb.SearchResponse(
            query=payload.get("query", request.query or ""),
            results=[_summary(row) for row in payload.get("results") or []],
        )

    async def Recommend(self, request, context):
        seeds = [request.video_id] if request.video_id else []
        seeds += [seed for seed in request.seed_video_ids if seed]
        payload = await asyncio.to_thread(
            PIPELINE.recomendar, seeds, request.limit or 10
        )
        return pb.RecommendResponse(
            seed_video_id=payload.get("seed_video_id", ""),
            recommendations=[
                _summary(row) for row in payload.get("recommendations") or []
            ],
            engine=payload.get("engine", "none"),
            weights=payload.get("weights")
            or {"name": 0.10, "artist": 0.05, "lyrics": 0.85},
        )

    async def GetTrack(self, request, context):
        song = await asyncio.to_thread(PIPELINE.cancion, request.video_id)
        if song is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Unknown video id")
        return pb.GetTrackResponse(track=_track(song, request.include_lyrics))

    async def ListTracks(self, request, context):
        songs = await asyncio.to_thread(PIPELINE.canciones)
        if request.language:
            songs = [song for song in songs if song["language"] == request.language]
        offset = max(0, int(request.offset or 0))
        limit = max(1, min(int(request.limit or 60), 200))
        return pb.ListTracksResponse(
            total=len(songs),
            tracks=[_track(song) for song in songs[offset : offset + limit]],
        )

    async def GetLyrics(self, request, context):
        song = await asyncio.to_thread(PIPELINE.cancion, request.video_id)
        if song is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Unknown video id")
        lineas = [
            pb.LyricsLine(time_ms=0, text=linea)
            for linea in str(song.get("lyrics") or "").splitlines()
            if linea.strip()
        ]
        return pb.GetLyricsResponse(
            video_id=request.video_id,
            synced=False,
            lines=lineas,
            raw=str(song.get("lyrics") or ""),
            language=str(song.get("language") or ""),
        )

    async def Stream(self, request, context):
        song = await asyncio.to_thread(PIPELINE.cancion, request.video_id)
        if song is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Unknown video id")
        return pb.StreamResponse(
            video_id=request.video_id,
            url=f"/api/player/proxy/{request.video_id}?kind=audio",
            duration=0.0,
            expires_at=int(time.time()) + 3600,
        )

    async def IndexPlaylist(self, request, context):
        if not (request.playlist_url or "").strip():
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "playlist_url is required"
            )
        try:
            url = ingest.validar_url_playlist(request.playlist_url)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        job = await PIPELINE.encolar(
            url, request.limit or None, request.source or "local-ui"
        )
        return _job(job)

    async def QueuePlaylists(self, request, context):
        jobs = []
        for raw in request.playlist_urls:
            try:
                url = ingest.validar_url_playlist(raw)
            except ValueError as exc:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            job = await PIPELINE.encolar(
                url, request.limit or None, request.source or "local-ui"
            )
            jobs.append(_job(job))
        return pb.QueuePlaylistsResponse(
            jobs=jobs,
            queue_size=sum(
                1 for j in PIPELINE.jobs.values() if j["status"] == "queued"
            ),
        )

    async def GetJob(self, request, context):
        job = PIPELINE.jobs.get(request.job_id)
        if job is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Unknown job id")
        return pb.GetJobResponse(job=_job(job))

    async def ExtractVideoIds(self, request, context):
        try:
            url = ingest.validar_url_playlist(request.playlist_url)
            videos = await asyncio.to_thread(
                ingest.extraer_video_ids, url, request.limit or None
            )
        except (ValueError, RuntimeError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return pb.ExtractVideoIdsResponse(
            count=len(videos), video_ids=[video_id for video_id, _ in videos]
        )

    async def GetIndexStats(self, request, context):
        return _stats()

    async def WatchIndexStats(self, request, context):
        intervalo = max(2, min(int(request.interval_seconds or 5), 60))
        while True:
            yield _stats()
            await asyncio.sleep(intervalo)

    async def GetFailedSongs(self, request, context):
        return pb.GetFailedSongsResponse(
            total=0, cached_lyrics=0, max_attempts=0, retry_interval_seconds=0
        )

    async def RetryFailed(self, request, context):
        return pb.RetryFailedResponse(
            started=False,
            already_running=False,
            message="The standalone indexer keeps no retry ledger; resubmit the playlist.",
        )

    async def MatrixPreview(self, request, context):
        recorte = await asyncio.to_thread(PIPELINE.matriz_preview, request.size or 12)
        ids = recorte["ids"]
        filas = [pb.MatrixPreviewRow(values=valores) for valores in recorte["matriz"]]
        canciones = [
            _summary(
                {
                    "video_id": PIPELINE.indexer.ids[i],
                    "title": PIPELINE.indexer.titulos[i],
                    "artist": PIPELINE.indexer.artistas[i],
                    "language": PIPELINE.indexer.idiomas[i],
                }
            )
            for i in ids
        ]
        return pb.MatrixPreviewResponse(
            shape=[len(ids), len(ids)],
            size=len(ids),
            songs=canciones,
            matrices={
                "lyrics": pb.MatrixPreview(shape=[len(ids), len(ids)], rows=filas)
            },
            weights={"name": 0.10, "artist": 0.05, "lyrics": 0.85},
        )

    async def IndexPlaylistFromBot(self, request, context):
        try:
            url = ingest.validar_url_playlist(request.playlist_url)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        job = await PIPELINE.encolar(
            url, request.limit or None, f"bot:{request.source_bot or 'unknown'}"
        )
        return pb.IndexPlaylistFromBotResponse(
            accepted=True, job=_job(job), job_status_url=str(job["job_id"])
        )


class LocalIndexerServicer(pb_grpc.LirifyIndexerServiceServicer):
    async def PublishToCloud(self, request, context):
        try:
            resultado = await asyncio.to_thread(PIPELINE.publicar)
        except Exception as exc:  # noqa: BLE001 - surfaced to the dashboard
            await context.abort(grpc.StatusCode.INTERNAL, f"publish failed: {exc}")
        return pb.PublishToCloudResponse(
            published=True,
            songs=int(resultado.get("songs") or 0),
            vectors=int(resultado.get("vectors") or 0),
            vocabulary_terms=int(PIPELINE.indexer.estadisticas()["vocabulary_size"]),
            inverted_terms=int(PIPELINE.indexer.estadisticas()["inverted_terms"]),
            directory=(os.environ.get("LOCAL_INDEX_DIR") or "").strip(),
            message=(
                f"Published {resultado.get('songs', 0)} songs and "
                f"{resultado.get('vectors', 0)} embeddings "
                f"(revision {resultado.get('revision', 0)})"
            ),
            published_at=PIPELINE.publicado_en,
            unchanged=False,
        )

    async def GetLocalIndex(self, request, context):
        datos = PIPELINE.estadisticas()
        return pb.GetLocalIndexResponse(
            info=pb.LocalIndexInfo(
                directory=(os.environ.get("LOCAL_INDEX_DIR") or "").strip(),
                tokenizer=str(datos.get("embedding_model") or ""),
                tokenizer_backend="sentence-transformers",
                embedding_provider=str(datos.get("embedding_provider") or ""),
                documents=int(datos.get("songs_indexed") or 0),
                vocabulary_terms=int(datos.get("vocabulary_size") or 0),
                inverted_terms=int(datos.get("inverted_terms") or 0),
                vocabulary_bytes=0,
                inverted_index_bytes=0,
                updated_at=PIPELINE.publicado_en,
                vocabulary_path="",
                inverted_index_path="",
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
    except Exception as exc:  # noqa: BLE001 - optional dependency
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
    pb_grpc.add_LirifyServiceServicer_to_server(LocalServicer(), server)
    pb_grpc.add_LirifyIndexerServiceServicer_to_server(LocalIndexerServicer(), server)
    _install_reflection(server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    print(
        f"[lirify] local-indexer gRPC listening on :{port} "
        f"(model={PIPELINE.indexer.modelo_id}, autopublish={PIPELINE.auto_publicar})",
        flush=True,
    )
    return server


async def start_admin_server() -> tuple[uvicorn.Server, asyncio.Task]:
    config = uvicorn.Config(
        admin_api.build_app(PIPELINE),
        host="0.0.0.0",
        port=int(os.environ.get("ADMIN_PORT", "8080")),
        log_level=os.environ.get("ADMIN_LOG_LEVEL", "warning"),
        access_log=False,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    print(
        f"[lirify] database admin listening on :{config.port} (localhost only)",
        flush=True,
    )
    return server, task


async def serve() -> None:
    server = await start_local_server()
    admin, admin_task = await start_admin_server()
    carga = asyncio.create_task(PIPELINE.arrancar())
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover
            pass
    await stop.wait()
    admin.should_exit = True
    carga.cancel()
    await PIPELINE.detener()
    await server.stop(grace=5)
    try:
        await asyncio.wait_for(admin_task, timeout=5)
    except (TimeoutError, asyncio.CancelledError):
        admin_task.cancel()


def main_entry() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main_entry()
