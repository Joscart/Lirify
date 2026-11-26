"""Playlist ingestion for the local indexer.

This is the only place that scrapes: yt-dlp resolves a playlist into video ids,
noembed resolves the title/artist pair, and `lyrics_sources.fetch_lyrics` walks
the nine lyric providers. The result feeds `core.Indexer`; nothing here talks to
MongoDB or Qdrant.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from lyrics_sources import fetch_lyrics

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

Progreso = Callable[..., None] | None


def validar_url_playlist(raw: str) -> str:
    """Return the canonical playlist URL or raise ValueError."""
    value = (raw or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must start with https://")
    host = (parsed.netloc or "").lower().split(":")[0]
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            f"Only public YouTube hosts are accepted, got {host or 'nothing'}"
        )
    playlist_id = (parse_qs(parsed.query).get("list") or [""])[0]
    if not playlist_id:
        raise ValueError("The URL has no list= parameter; a playlist id is required")
    if not PLAYLIST_ID_RE.fullmatch(playlist_id):
        raise ValueError("Malformed playlist id")
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def extraer_video_ids(url: str, limite: int | None = None) -> list[tuple[str, float]]:
    comando = [
        "yt-dlp",
        "--flat-playlist",
        "--no-warnings",
        "--no-cache-dir",
        "--print",
        "%(id)s\t%(duration)s",
        url,
    ]
    salida = subprocess.run(
        comando, capture_output=True, text=True, timeout=600, check=False
    )
    if salida.returncode != 0 and not salida.stdout.strip():
        raise RuntimeError(f"yt-dlp failed: {salida.stderr[-1000:]}")

    vistos: list[tuple[str, float]] = []
    ids: set[str] = set()
    for linea in salida.stdout.splitlines():
        partes = linea.split("\t")
        video_id = partes[0].strip()
        if not VIDEO_ID_RE.fullmatch(video_id) or video_id in ids:
            continue
        ids.add(video_id)
        duracion = 0.0
        if len(partes) > 1:
            try:
                duracion = float(partes[1])
            except ValueError:
                duracion = 0.0
        vistos.append((video_id, duracion))
        if limite and len(vistos) >= limite:
            break
    if not vistos:
        raise RuntimeError("No video IDs found in that URL")
    return vistos


def metadatos(video_id: str) -> dict[str, str]:
    try:
        respuesta = requests.get(
            "https://noembed.com/embed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}"},
            timeout=15,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()
        return {
            "title": datos.get("title", ""),
            "author": datos.get("author_name", ""),
        }
    except (requests.RequestException, ValueError):
        return {"title": "", "author": ""}


def parsear_titulo(titulo: str, autor: str) -> tuple[str, str]:
    titulo = re.sub(
        r"\s*\((?:official\s*)?(?:lyric|lyrics|audio|video|music)\s*(?:video)?\)",
        "",
        titulo,
        flags=re.IGNORECASE,
    )
    titulo = re.sub(
        r"\s*\[(?:official\s*)?(?:lyric|lyrics|audio|video|music)\s*(?:video)?\]",
        "",
        titulo,
        flags=re.IGNORECASE,
    )
    if " - " in titulo:
        artista, cancion = titulo.split(" - ", 1)
    else:
        artista, cancion = autor, titulo
    artista = re.sub(r"\s*-\s*topic$", "", artista or "", flags=re.IGNORECASE).strip()
    cancion = re.sub(
        r"\s*\((?:official\s*)?(?:lyric|lyrics|audio|video|music)[^)]*\)",
        "",
        cancion,
        flags=re.IGNORECASE,
    ).strip()
    return artista.strip(), cancion.strip()


def detectar_idioma(texto: str) -> str:
    limpio = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\]", " ", texto or "")
    limpio = re.sub(r"<[^>]+>", " ", limpio).strip()
    if len(limpio) < 8:
        return "unknown"
    try:
        from langdetect import detect_langs
        from langdetect.lang_detect_exception import LangDetectException

        ranked = detect_langs(limpio)
    except (ImportError, LangDetectException):
        return "unknown"
    if not ranked:
        return "unknown"
    return ranked[0].lang


def scrape_cancion(video_id: str, duracion: float = 0.0) -> dict[str, Any] | None:
    meta = metadatos(video_id)
    artista, track = parsear_titulo(meta["title"], meta["author"])
    letra, backend = fetch_lyrics(
        track, artista, video_id=video_id, duration=duracion or None
    )
    if not (letra or "").strip():
        return None
    return {
        "video_id": video_id,
        "title": meta["title"],
        "track": track,
        "artist": artista,
        "language": detectar_idioma(letra),
        "lyrics": letra,
        "backend": backend,
        "duration": duracion or None,
    }


def cargar_playlist(
    url: str,
    limite: int | None = None,
    progreso: Progreso = None,
) -> list[dict[str, Any]]:
    """Resolve a playlist and return every song that has lyrics."""
    url = validar_url_playlist(url)
    videos = extraer_video_ids(url, limite)
    if progreso:
        progreso("extract", count=len(videos), url=url)

    canciones: list[dict[str, Any]] = []
    for indice, (video_id, duracion) in enumerate(videos, start=1):
        if progreso:
            progreso(
                "scrape",
                video_id=video_id,
                position=indice,
                total=len(videos),
            )
        cancion = scrape_cancion(video_id, duracion)
        if cancion is None:
            if progreso:
                progreso("skip", video_id=video_id, reason="no lyrics")
            continue
        canciones.append(cancion)

    if progreso:
        progreso("scraped", songs=len(canciones), total=len(videos))
    return canciones
