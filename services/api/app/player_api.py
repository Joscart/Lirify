"""Player-facing API for the Astro client.

This module is **additive**. It never touches the ranking, search, recommendation
or indexing algorithms in ``main.py``: it only reshapes the state they already
produce into what a player UI needs (cards, playlists, timed lyrics, stream URLs
and a server-side playback clock).

Everything here is read-only against the committed index. Resolved durations are
persisted through the shared store (MongoDB Atlas, or the in-memory dev store),
never in a local file, so Cloud Run cold starts keep serving. The playback clock
stays in process memory: a lost playhead is acceptable, a lost duration is not.
"""

import bisect
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from store import get_store

STORE = get_store()

YTDLP = shutil.which("yt-dlp") or "yt-dlp"
UA = "Lirify Player v1.0"

# Resolved media URLs are short-lived on YouTube's side; cache them for a while so
# replaying a track is instant. Keyed by (video_id, kind).
STREAM_TTL = 90 * 60
STREAM_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
STREAM_LOCKS: Dict[Tuple[str, str], threading.Lock] = {}
STREAM_LOCKS_GUARD = threading.Lock()

DURATIONS: Dict[str, float] = {}
_LYRIC_CACHE: Dict[Tuple[str, int], Dict[str, Any]] = {}
_SESSION_LOCK = threading.Lock()
_SESSION: Dict[str, Any] = {}

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Español",
    "ja": "日本語",
    "ko": "한국어",
    "pt": "Português",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "ru": "Русский",
    "zh": "中文",
    "id": "Bahasa Indonesia",
    "tl": "Tagalog",
    "so": "Soomaali",
    "sw": "Kiswahili",
    "hi": "हिन्दी",
    "ar": "العربية",
    "tr": "Türkçe",
    "nl": "Nederlands",
    "pl": "Polski",
    "uk": "Українська",
    "vi": "Tiếng Việt",
    "th": "ไทย",
    "unknown": "Unknown",
}


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _load_media_cache() -> None:
    """Durations resolved by yt-dlp are durable state: read them from the store."""
    try:
        for key, value in STORE.durations_all().items():
            try:
                DURATIONS[key] = float(value)
            except (TypeError, ValueError):
                continue
    except Exception as exc:  # pragma: no cover - Atlas unreachable
        print(f"[lirify] duration cache unavailable: {exc}", flush=True)


def _save_media_duration(video_id: str, duration: float) -> None:
    try:
        STORE.duration_put(video_id, duration)
    except Exception as exc:  # pragma: no cover
        print(f"[lirify] duration write failed: {exc}", flush=True)


_load_media_cache()


def slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return value or "unknown"


def thumb(video_id: str, size: str = "hq") -> str:
    if not video_id:
        return ""
    return f"https://i.ytimg.com/vi/{video_id}/{size}default.jpg"


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get((code or "").lower(), (code or "?").upper())


# ---------------------------------------------------------------------------
# Lyrics: LRC / enhanced LRC -> timed lines (and word timings when present)
# ---------------------------------------------------------------------------

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[(ar|ti|al|by|offset|length|re|ve|au):(.*)\]$", re.I)
_WORD_TAG = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")


def _fraction_ms(raw: Optional[str]) -> int:
    if not raw:
        return 0
    if len(raw) == 1:
        return int(raw) * 100
    if len(raw) == 2:
        return int(raw) * 10
    return int(raw[:3])


def _tag_seconds(match: re.Match) -> float:
    minutes, seconds, fraction = match.groups()
    return int(minutes) * 60 + int(seconds) + _fraction_ms(fraction) / 1000.0


def parse_lyrics(raw: str) -> Dict[str, Any]:
    """Return ``{synced, offset, lines:[{t,text,words?}], duration}``.

    Handles plain lyrics, LRC with multiple stamps per line, enhanced LRC word
    tags and the ``[offset:]`` metadata tag. Never raises on malformed input.
    """
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    if not text.strip():
        return {"synced": False, "offset": 0, "lines": [], "duration": 0.0}

    text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.I)
    offset_ms = 0
    entries: List[Tuple[float, int, Optional[List[Dict[str, Any]]], str]] = []
    order = 0

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        meta = _META_TAG.match(stripped)
        if meta:
            if meta.group(1).lower() == "offset":
                try:
                    offset_ms = int(float(meta.group(2).strip()))
                except ValueError:
                    pass
            continue

        stamps = list(_TIME_TAG.finditer(stripped))
        if not stamps:
            entries.append((0.0, order, None, stripped))
            order += 1
            continue

        body_start = stamps[-1].end()
        body = stripped[body_start:]
        words: Optional[List[Dict[str, Any]]] = None
        word_tags = list(_WORD_TAG.finditer(body))
        if word_tags:
            words = []
            for index, tag in enumerate(word_tags):
                start = tag.end()
                end = word_tags[index + 1].start() if index + 1 < len(word_tags) else len(body)
                chunk = body[start:end].strip()
                if chunk:
                    words.append({"t": round(_tag_seconds(tag), 3), "text": chunk})
            body = _WORD_TAG.sub("", body)
        body = re.sub(r"\s+", " ", body).strip()
        if not body:
            continue
        for stamp in stamps:
            entries.append((_tag_seconds(stamp), order, words, body))
            order += 1

    if not entries:
        return {"synced": False, "offset": 0, "lines": [], "duration": 0.0}

    has_times = bool(_TIME_TAG.search(text))
    entries.sort(key=lambda e: (e[0] if has_times else float(e[1]), e[1]))

    lines: List[Dict[str, Any]] = []
    seen = set()
    for start, _order, words, body in entries:
        seconds = max(0.0, start + offset_ms / 1000.0) if has_times else None
        signature = (round(seconds, 3) if seconds is not None else None, body)
        if signature in seen:
            continue
        seen.add(signature)
        row: Dict[str, Any] = {
            "t": round(seconds, 3) if seconds is not None else None,
            "text": body,
        }
        if words:
            row["words"] = [
                {"t": round(max(0.0, w["t"] + offset_ms / 1000.0), 3), "text": w["text"]}
                for w in words
            ]
        lines.append(row)

    duration = 0.0
    if has_times and lines:
        duration = round((lines[-1]["t"] or 0.0) + 4.0, 3)
    return {
        "synced": bool(has_times),
        "offset": offset_ms,
        "lines": lines,
        "duration": duration,
    }


def lyrics_for(song: Dict[str, Any]) -> Dict[str, Any]:
    key = (song.get("video_id", ""), len(song.get("lyrics") or ""))
    cached = _LYRIC_CACHE.get(key)
    if cached is not None:
        return cached
    parsed = parse_lyrics(song.get("lyrics") or "")
    parsed["source"] = song.get("backend") or "unknown"
    parsed["language"] = song.get("language") or "unknown"
    if len(_LYRIC_CACHE) > 400:
        _LYRIC_CACHE.clear()
    _LYRIC_CACHE[key] = parsed
    return parsed


def estimated_duration(song: Dict[str, Any]) -> Tuple[float, bool]:
    video_id = song.get("video_id", "")
    known = DURATIONS.get(video_id)
    if known:
        return round(float(known), 2), False
    parsed = lyrics_for(song)
    if parsed.get("duration"):
        return round(float(parsed["duration"]), 2), True
    return 0.0, True


# ---------------------------------------------------------------------------
# Track / artist / playlist shaping
# ---------------------------------------------------------------------------

def _song_list(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(state.get("songs") or [])


def track_brief(song: Dict[str, Any]) -> Dict[str, Any]:
    video_id = song.get("video_id", "")
    duration, estimated = estimated_duration(song)
    parsed = lyrics_for(song)
    return {
        "id": video_id,
        "video_id": video_id,
        "kind": "track",
        "title": song.get("track") or song.get("title") or video_id,
        "youtube_title": song.get("title") or song.get("track") or "",
        "artist": song.get("artist") or "Unknown artist",
        "artist_id": slugify(song.get("artist") or "unknown"),
        "language": song.get("language") or "unknown",
        "language_name": language_name(song.get("language") or "unknown"),
        "lyrics_source": song.get("backend") or "unknown",
        "thumb": thumb(video_id, "hq"),
        "art": thumb(video_id, "maxres"),
        "poster": thumb(video_id, "hq"),
        "duration": duration,
        "duration_estimated": estimated,
        "synced_lyrics": bool(parsed.get("synced")),
        "lines": len(parsed.get("lines") or []),
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
    }


def _track_from_index(state: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    songs = _song_list(state)
    if index < 0 or index >= len(songs):
        return None
    return songs[index]


def _centrality(state: Dict[str, Any]) -> List[float]:
    songs = _song_list(state)
    matrix = (state.get("matrices") or {}).get("unified")
    if matrix is None or not songs:
        return [0.0] * len(songs)
    try:
        if matrix.shape[0] != len(songs):
            return [0.0] * len(songs)
        totals = matrix.sum(axis=1)
        peak = float(totals.max()) or 1.0
        return [float(v) / peak for v in totals]
    except Exception:
        return [0.0] * len(songs)


def artists_payload(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    songs = _song_list(state)
    centrality = _centrality(state)
    groups: Dict[str, Dict[str, Any]] = {}
    for index, song in enumerate(songs):
        name = (song.get("artist") or "Unknown artist").strip() or "Unknown artist"
        entry = groups.setdefault(
            name,
            {
                "id": slugify(name),
                "name": name,
                "tracks": [],
                "languages": {},
                "score": 0.0,
            },
        )
        entry["tracks"].append(index)
        lang = song.get("language") or "unknown"
        entry["languages"][lang] = entry["languages"].get(lang, 0) + 1
        entry["score"] += centrality[index]
    out = []
    for entry in groups.values():
        top = max(entry["tracks"], key=lambda i: centrality[i]) if entry["tracks"] else None
        cover_song = songs[top] if top is not None else None
        language = max(entry["languages"], key=entry["languages"].get)
        out.append(
            {
                "id": entry["id"],
                "kind": "artist",
                "name": entry["name"],
                "title": entry["name"],
                "count": len(entry["tracks"]),
                "languages": entry["languages"],
                "language": language,
                "language_name": language_name(language),
                "cover": thumb(cover_song.get("video_id", ""), "hq") if cover_song else "",
                "art": thumb(cover_song.get("video_id", ""), "maxres") if cover_song else "",
                "top_track": track_brief(cover_song) if cover_song else None,
                "score": round(entry["score"], 4),
            }
        )
    out.sort(key=lambda a: (-a["count"], -a["score"], a["name"].lower()))
    return out


def _playlist_catalog(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    songs = _song_list(state)
    centrality = _centrality(state)
    order = list(range(len(songs)))
    by_score = sorted(order, key=lambda i: -centrality[i])
    fresh = list(reversed(order))[:40]

    catalogs: List[Dict[str, Any]] = [
        {
            "id": "for-you",
            "title": "Made for you",
            "subtitle": "The centre of your indexed library",
            "kind": "playlist",
            "tag": "Mix",
            "indexes": by_score[:40],
        },
        {
            "id": "deep-cuts",
            "title": "Deep cuts",
            "subtitle": "Least connected songs in the index",
            "kind": "playlist",
            "tag": "Discover",
            "indexes": list(reversed(by_score))[:40],
        },
        {
            "id": "fresh",
            "title": "Fresh in the index",
            "subtitle": "The most recently committed tracks",
            "kind": "playlist",
            "tag": "New",
            "indexes": fresh,
        },
    ]

    languages: Dict[str, List[int]] = {}
    for index, song in enumerate(songs):
        languages.setdefault(song.get("language") or "unknown", []).append(index)
    for code, indexes in sorted(languages.items(), key=lambda kv: -len(kv[1])):
        if code == "unknown":
            continue
        catalogs.append(
            {
                "id": f"lang-{slugify(code)}",
                "title": f"{language_name(code)} essentials",
                "subtitle": f"{len(indexes)} indexed {'song' if len(indexes) == 1 else 'songs'}",
                "kind": "playlist",
                "tag": language_name(code),
                "indexes": sorted(indexes, key=lambda i: -centrality[i]),
            }
        )

    # One artist playlist per prolific artist, so the card grid has real variety.
    artists = artists_payload(state)
    by_name: Dict[str, List[int]] = {}
    for index, song in enumerate(songs):
        by_name.setdefault((song.get("artist") or "Unknown artist").strip(), []).append(index)
    for artist in artists[:12]:
        if artist["count"] < 3:
            continue
        catalogs.append(
            {
                "id": f"artist-{artist['id']}",
                "title": artist["name"],
                "subtitle": f"Artist radio · {artist['count']} tracks",
                "kind": "playlist",
                "tag": "Artist",
                "indexes": sorted(
                    by_name.get(artist["name"], []), key=lambda i: -centrality[i]
                ),
            }
        )

    for catalog in catalogs:
        indexes = catalog.pop("indexes")
        cover_indexes = indexes[:4] if len(indexes) >= 4 else indexes
        catalog["track_ids"] = [songs[i]["video_id"] for i in indexes]
        catalog["count"] = len(indexes)
        catalog["covers"] = [
            thumb(songs[i].get("video_id", ""), "hq") for i in cover_indexes
        ]
        catalog["cover"] = catalog["covers"][0] if catalog["covers"] else ""
        seconds = sum(estimated_duration(songs[i])[0] for i in indexes)
        catalog["duration"] = round(seconds, 2)
        catalog["synced"] = sum(
            1 for i in indexes if lyrics_for(songs[i]).get("synced")
        )
    return catalogs


def playlist_by_id(state: Dict[str, Any], playlist_id: str) -> Optional[Dict[str, Any]]:
    for catalog in _playlist_catalog(state):
        if catalog["id"] == playlist_id:
            return catalog
    return None


def preview_matrices(current: Dict[str, Any], size: int = 12) -> Optional[Dict[str, Any]]:
    """A tiny, centrality-ranked slice of every similarity matrix.

    The full ``/matrices`` document is O(n²) per matrix (hundreds of MB on a real
    library); the admin dashboards only need a readable heatmap. Shared by the REST
    route and the gRPC ``MatrixPreview`` RPC.
    """
    songs = _song_list(current)
    matrices = current.get("matrices") or {}
    if not songs or not matrices:
        return None
    total = len(songs)
    size = max(4, min(int(size or 12), 24, total))
    centrality = _centrality(current)
    indices = sorted(range(total), key=lambda index: -centrality[index])[:size]
    out: Dict[str, Any] = {
        "shape": [total, total],
        "size": size,
        "weights": (current.get("build") or {}).get("weights") or {},
        "indices": indices,
        "songs": [
            {
                "video_id": songs[i].get("video_id", ""),
                "title": songs[i].get("track") or songs[i].get("title") or "",
                "artist": songs[i].get("artist") or "",
                "language": songs[i].get("language") or "",
            }
            for i in indices
        ],
        "matrices": {},
    }
    for name, matrix in matrices.items():
        try:
            if matrix.shape[0] != total:
                continue
            out["matrices"][name] = {
                "shape": [total, total],
                "values": [
                    [round(float(matrix[row, column]), 4) for column in indices]
                    for row in indices
                ],
            }
        except Exception:
            continue
    return out


def build_router(
    get_state: Callable[[], Dict[str, Any]],
    search_fn: Callable[..., Dict[str, Any]],
    recommend_fn: Callable[..., Dict[str, Any]],
) -> APIRouter:
    router = APIRouter(prefix="/api/player", tags=["player"])

    # -- search / shape helpers -------------------------------------------------

    def state() -> Dict[str, Any]:
        return get_state() or {}

    def enrich_result(result: Dict[str, Any], song: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if song is None:
            video_id = result.get("video_id", "")
            return {
                "id": video_id,
                "video_id": video_id,
                "kind": "track",
                "title": result.get("title") or video_id,
                "artist": result.get("artist") or "Unknown artist",
                "artist_id": slugify(result.get("artist") or "unknown"),
                "language": result.get("language") or "unknown",
                "language_name": language_name(result.get("language") or "unknown"),
                "thumb": thumb(video_id, "hq"),
                "art": thumb(video_id, "maxres"),
                "duration": 0,
                "duration_estimated": True,
                "synced_lyrics": False,
                "score": result.get("score"),
            }
        brief = track_brief(song)
        brief["score"] = result.get("score")
        brief["match"] = int(round(min(1.0, max(0.0, float(result.get("score") or 0))) * 100))
        return brief

    def snippet_for(song: Dict[str, Any], query: str) -> str:
        words = [w for w in re.split(r"\W+", (query or "").lower()) if len(w) > 2]
        if not words or not song:
            return ""
        for line in (song.get("lyrics") or "").replace("\r", "").split("\n"):
            plain = _TIME_TAG.sub("", line).strip()
            if not plain:
                continue
            lowered = plain.lower()
            if any(word in lowered for word in words):
                if len(plain) > 160:
                    plain = plain[:157].rstrip() + "…"
                return plain
        return ""

    def song_by_id(video_id: str) -> Optional[Dict[str, Any]]:
        for song in state().get("songs") or []:
            if song.get("video_id") == video_id:
                return song
        return None

    # -- library ---------------------------------------------------------------

    @router.get("/bootstrap")
    def bootstrap():
        current = state()
        songs = _song_list(current)
        artists = artists_payload(current)
        playlists = _playlist_catalog(current)
        centrality = _centrality(current)
        order = sorted(range(len(songs)), key=lambda i: -centrality[i])
        build = current.get("build") or {}
        languages: Dict[str, int] = {}
        for song in songs:
            code = song.get("language") or "unknown"
            languages[code] = languages.get(code, 0) + 1
        language_chips = [
            {
                "code": code,
                "name": language_name(code),
                "count": count,
            }
            for code, count in sorted(languages.items(), key=lambda kv: -kv[1])
        ]

        hero = None
        if order:
            hero_song = songs[order[0]]
            hero = track_brief(hero_song)
            hero["rank"] = 1
            hero["blurb"] = (
                f"{build.get('inverted_terms', 0):,} index terms · "
                f"{build.get('lyrics_tokens', 0):,} lyric tokens"
            )

        shelves: List[Dict[str, Any]] = []
        newest_first = list(range(len(songs)))[::-1][:14]
        fresh = [songs[i] for i in newest_first]
        shelves.append(
            {
                "id": "fresh",
                "title": "Fresh in the index",
                "subtitle": "Just committed to your library",
                "kind": "tracks",
                "items": [track_brief(s) for s in fresh],
            }
        )
        shelves.append(
            {
                "id": "for-you",
                "title": "Made for you",
                "subtitle": "Songs closest to the heart of your index",
                "kind": "tracks",
                "items": [track_brief(songs[i]) for i in order[:14]],
            }
        )
        shelves.append(
            {
                "id": "artists",
                "title": "Artists in your library",
                "subtitle": "The voices behind the lyrics you indexed",
                "kind": "artists",
                "items": artists[:14],
            }
        )
        shelves.append(
            {
                "id": "playlists",
                "title": "Playlists for you",
                "subtitle": "Built from the lyrics similarity model",
                "kind": "playlists",
                "items": playlists[:10],
            }
        )
        shelves.append(
            {
                "id": "videos",
                "title": "Music videos",
                "subtitle": "Every indexed track streams as video too",
                "kind": "videos",
                "items": [
                    {**track_brief(songs[i]), "kind": "video"} for i in order[3:11]
                ],
            }
        )

        return {
            "library": {
                "songs": len(songs),
                "artists": len(artists),
                "playlists": len(playlists),
                "languages": len([c for c in language_chips if c["code"] != "unknown"]),
                "videos": len(songs),
                "terms": build.get("inverted_terms", 0),
                "tokens": build.get("lyrics_tokens", 0),
                "synced": sum(1 for s in songs if lyrics_for(s).get("synced")),
                "weights": build.get("weights") or {},
                "generated_at": time.time(),
            },
            "hero": hero,
            "languages": language_chips,
            "shelves": [s for s in shelves if s["items"]],
            "artists": artists[:40],
            "playlists": playlists,
            "top_tracks": [track_brief(songs[i]) for i in order[:50]],
            "capabilities": {
                "streaming": True,
                "video": True,
                "synced_lyrics": True,
                "resolver": "yt-dlp",
            },
        }

    @router.get("/tracks")
    def tracks(offset: int = 0, limit: int = 60, artist: str = "", language: str = ""):
        songs = _song_list(state())
        items = songs
        if artist:
            items = [
                s for s in items if slugify(s.get("artist") or "") == slugify(artist)
            ]
        if language:
            items = [s for s in items if (s.get("language") or "") == language]
        total = len(items)
        offset = max(0, offset)
        limit = max(1, min(limit, 300))
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "tracks": [track_brief(s) for s in items[offset : offset + limit]],
        }

    @router.get("/track/{video_id}")
    def track(video_id: str):
        song = song_by_id(video_id)
        if not song:
            raise HTTPException(404, "Unknown video id")
        brief = track_brief(song)
        parsed = lyrics_for(song)
        brief["lyrics"] = {
            "source": parsed.get("source"),
            "synced": parsed.get("synced", False),
            "offset": parsed.get("offset", 0),
            "lines": parsed.get("lines", []),
        }
        return brief

    @router.get("/track/{video_id}/lyrics")
    def track_lyrics(video_id: str):
        song = song_by_id(video_id)
        if not song:
            raise HTTPException(404, "Unknown video id")
        parsed = lyrics_for(song)
        duration, estimated = estimated_duration(song)
        return {
            "video_id": video_id,
            "title": song.get("track") or video_id,
            "artist": song.get("artist") or "",
            "source": parsed.get("source"),
            "language": parsed.get("language"),
            "synced": parsed.get("synced", False),
            "offset": parsed.get("offset", 0),
            "duration": duration,
            "duration_estimated": estimated,
            "lines": parsed.get("lines", []),
        }

    # -- search / recommendations (delegated to the untouched core) -------------

    @router.get("/search")
    def search(q: str, limit: int = 24):
        query = (q or "").strip()
        if not query:
            return {"query": query, "top": None, "tracks": [], "artists": [], "snippet": ""}
        limit = max(1, min(limit, 60))
        core = search_fn(query, limit)
        results = core.get("results") or []
        enriched = []
        for result in results:
            song = song_by_id(result.get("video_id", ""))
            item = enrich_result(result, song)
            if song:
                snippet = snippet_for(song, query)
                if snippet:
                    item["snippet"] = snippet
            enriched.append(item)

        songs = _song_list(state())
        needle = query.lower()
        artists = [
            artist
            for artist in artists_payload(state())
            if needle in artist["name"].lower()
        ][:8]

        return {
            "query": query,
            "top": enriched[0] if enriched else (artists[0] if artists else None),
            "tracks": enriched,
            "artists": artists,
            "snippet": next((t.get("snippet") for t in enriched if t.get("snippet")), ""),
            "scanned": len(songs),
        }

    @router.get("/radio/{video_id}")
    def radio(video_id: str, limit: int = 16):
        seed_song = song_by_id(video_id)
        if not seed_song:
            raise HTTPException(404, "Unknown video id")
        core = recommend_fn(video_id, max(1, min(limit, 50)))
        items = []
        for result in core.get("recommendations") or []:
            song = song_by_id(result.get("video_id", ""))
            item = enrich_result(result, song)
            item["match"] = int(
                round(min(1.0, max(0.0, float(result.get("score") or 0))) * 100)
            )
            items.append(item)
        return {
            "seed": track_brief(seed_song),
            "score_weights": (state().get("build") or {}).get("weights") or {},
            "recommendations": items,
        }

    @router.get("/matrices/preview")
    def matrices_preview(size: int = 12):
        out = preview_matrices(state(), size)
        if out is None:
            raise HTTPException(404, "Nothing indexed yet")
        return out

    @router.get("/artists")
    def artists():
        return {"artists": artists_payload(state())}

    @router.get("/artist/{artist_id}")
    def artist(artist_id: str):
        current = state()
        songs = _song_list(current)
        artists = artists_payload(current)
        match = next(
            (a for a in artists if a["id"] == artist_id or a["id"] == slugify(artist_id)),
            None,
        )
        if not match:
            raise HTTPException(404, "Unknown artist")
        indexes = [
            i for i, s in enumerate(songs)
            if slugify(s.get("artist") or "unknown") == match["id"]
        ]
        centrality = _centrality(current)
        ordered = sorted(indexes, key=lambda i: -centrality[i])
        similar = _similar_artists(current, match["name"])
        return {
            "artist": match,
            "tracks": [track_brief(songs[i]) for i in ordered],
            "similar": similar,
        }

    def _similar_artists(current: Dict[str, Any], artist_name: str) -> List[Dict[str, Any]]:
        songs = _song_list(current)
        matrix = (current.get("matrices") or {}).get("unified")
        if matrix is None:
            return []
        try:
            rows = [
                i for i, s in enumerate(songs)
                if (s.get("artist") or "").strip() == artist_name
            ]
            if not rows:
                return []
            agg = matrix[rows].sum(axis=0)
            scores: Dict[str, float] = {}
            for index, song in enumerate(songs):
                name = (song.get("artist") or "").strip()
                if not name or name == artist_name:
                    continue
                scores[name] = scores.get(name, 0.0) + float(agg[index])
        except Exception:
            return []
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:8]
        catalog = {a["name"]: a for a in artists_payload(current)}
        return [catalog[name] for name, _ in ranked if name in catalog]

    @router.get("/playlists")
    def playlists():
        return {"playlists": _playlist_catalog(state())}

    @router.get("/playlist/{playlist_id}")
    def playlist(playlist_id: str, offset: int = 0, limit: int = 200):
        current = state()
        songs = _song_list(current)
        found = playlist_by_id(current, playlist_id)
        if not found:
            raise HTTPException(404, "Unknown playlist")
        by_id = {s.get("video_id"): s for s in songs}
        ordered = [by_id[vid] for vid in found.get("track_ids", []) if vid in by_id]
        offset = max(0, offset)
        limit = max(1, min(limit, 2000))
        return {
            "playlist": found,
            "total": len(ordered),
            "offset": offset,
            "tracks": [track_brief(s) for s in ordered[offset : offset + limit]],
        }

    @router.get("/videos")
    def videos(offset: int = 0, limit: int = 60):
        songs = _song_list(state())
        centrality = _centrality(state())
        ordered = sorted(range(len(songs)), key=lambda i: -centrality[i])
        slice_ = ordered[offset : offset + max(1, min(limit, 200))]
        return {
            "total": len(songs),
            "videos": [
                {**track_brief(songs[i]), "kind": "video"} for i in slice_
            ],
        }

    # -- streaming -------------------------------------------------------------

    def _resolve(video_id: str, kind: str) -> Dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
            raise HTTPException(400, "Invalid video id")
        key = (video_id, kind)
        cached = STREAM_CACHE.get(key)
        if cached and cached.get("expires_at", 0) > time.time():
            return cached
        with STREAM_LOCKS_GUARD:
            lock = STREAM_LOCKS.setdefault(key, threading.Lock())
        with lock:
            cached = STREAM_CACHE.get(key)
            if cached and cached.get("expires_at", 0) > time.time():
                return cached
            if kind == "video":
                fmt = "22/18/best[height<=720][ext=mp4]/best"
            else:
                fmt = "bestaudio[ext=m4a]/bestaudio"
            cmd = [
                YTDLP,
                "-f",
                fmt,
                "-g",
                "--no-warnings",
                "--no-cache-dir",
                "--no-playlist",
                "--print",
                "%(duration)s",
                f"https://www.youtube.com/watch?v={video_id}",
            ]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=90
                )
            except subprocess.TimeoutExpired:
                raise HTTPException(504, "Media resolver timed out")
            lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            url = next(
                (line for line in reversed(lines) if line.startswith("http")), ""
            )
            if proc.returncode != 0 or not url:
                detail = (proc.stderr or "yt-dlp could not resolve this video")[-400:]
                raise HTTPException(502, f"Media resolution failed: {detail}")
            duration = 0.0
            for line in lines:
                try:
                    duration = float(line)
                    break
                except ValueError:
                    continue
            if duration:
                DURATIONS[video_id] = duration
                _save_media_duration(video_id, duration)
            payload = {
                "video_id": video_id,
                "kind": kind,
                "url": url,
                "proxy_url": f"/api/player/proxy/{video_id}?kind={kind}",
                "expires_at": time.time() + STREAM_TTL,
                "duration": duration,
                "resolver": "yt-dlp",
            }
            STREAM_CACHE[key] = payload
            return payload

    @router.get("/stream/{video_id}")
    def stream(video_id: str, kind: str = "audio", probe: int = 0):
        try:
            payload = dict(_resolve(video_id, "video" if kind == "video" else "audio"))
        except HTTPException as exc:
            if probe:
                return {
                    "video_id": video_id,
                    "kind": kind,
                    "available": False,
                    "error": exc.detail,
                }
            raise
        payload.pop("url", None)  # the browser uses the proxy; URLs stay server-side
        payload["available"] = True
        return payload

    def _open_upstream(video_id: str, kind: str, range_header: str, retry: bool = True):
        payload = _resolve(video_id, kind)
        headers = {"User-Agent": UA}
        if range_header:
            headers["Range"] = range_header
        response = requests.get(
            payload["url"],
            headers=headers,
            stream=True,
            timeout=(15, 60),
            allow_redirects=True,
        )
        if response.status_code in (403, 410) and retry:
            response.close()
            STREAM_CACHE.pop((video_id, kind), None)
            return _open_upstream(video_id, kind, range_header, retry=False)
        return response

    @router.api_route("/proxy/{video_id}", methods=["GET", "HEAD"])
    def proxy(video_id: str, request: Request, kind: str = "audio"):
        kind = "video" if kind == "video" else "audio"
        upstream = _open_upstream(video_id, kind, request.headers.get("range", ""))
        if upstream.status_code >= 400:
            try:
                upstream.close()
            except Exception:
                pass
            raise HTTPException(502, f"Upstream media returned {upstream.status_code}")

        passthrough = {}
        for header in (
            "content-range",
            "accept-ranges",
            "etag",
            "last-modified",
        ):
            value = upstream.headers.get(header)
            if value:
                passthrough[header] = value
        content_length = upstream.headers.get("content-length")
        if content_length:
            passthrough["content-length"] = content_length

        media_type = upstream.headers.get(
            "content-type", "video/mp4" if kind == "video" else "audio/mp4"
        )
        passthrough.setdefault("accept-ranges", "bytes")
        # Byte ranges are stable for a resolved URL, and caching lets the browser
        # preload the next track for a near-gapless transition. The URL itself is
        # refreshed server-side long before this window expires.
        passthrough["cache-control"] = "private, max-age=600"

        if request.method == "HEAD":
            try:
                upstream.close()
            except Exception:
                pass
            return JSONResponse({}, status_code=upstream.status_code, headers=passthrough)

        def chunks():
            try:
                for chunk in upstream.iter_content(chunk_size=128 * 1024):
                    if chunk:
                        yield chunk
            finally:
                try:
                    upstream.close()
                except Exception:
                    pass

        return StreamingResponse(
            chunks(),
            status_code=upstream.status_code,
            headers=passthrough,
            media_type=media_type,
        )

    # -- playback session (server-tracked clock) --------------------------------

    class ProgressIn(BaseModel):
        video_id: str
        position: float = 0.0
        duration: Optional[float] = None
        state: str = "playing"

    def _session_payload(song: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with _SESSION_LOCK:
            session = dict(_SESSION)
        if not session:
            return {"active": False}
        elapsed = 0.0
        if session.get("state") == "playing":
            elapsed = max(0.0, time.monotonic() - session.get("monotonic", time.monotonic()))
        position = max(0.0, float(session.get("position", 0.0)) + elapsed)
        duration = session.get("duration") or 0.0
        if duration:
            position = min(position, float(duration))
        song = song or song_by_id(session.get("video_id", ""))
        parsed = lyrics_for(song) if song else {"lines": [], "synced": False}
        synced = [
            (i, line) for i, line in enumerate(parsed.get("lines") or [])
            if line.get("t") is not None
        ]
        line_index = None
        line = None
        next_line = None
        if synced:
            times = [entry[1]["t"] for entry in synced]
            cursor = bisect.bisect_right(times, position) - 1
            if cursor >= 0:
                line_index = synced[cursor][0]
                line = synced[cursor][1]
                if cursor + 1 < len(synced):
                    next_line = synced[cursor + 1][1]
        return {
            "active": True,
            "video_id": session.get("video_id"),
            "position": round(position, 3),
            "duration": duration or None,
            "state": session.get("state"),
            "synced": bool(synced),
            "line_index": line_index,
            "line": line,
            "next_line": next_line,
            "lines_total": len(parsed.get("lines") or []),
            "server_time": time.time(),
            "track": track_brief(song) if song else None,
        }

    @router.post("/session")
    def update_session(inp: ProgressIn):
        if inp.video_id and not re.fullmatch(r"[A-Za-z0-9_-]{11}", inp.video_id):
            raise HTTPException(400, "Invalid video id")
        state_value = "paused" if inp.state == "paused" else "playing"
        with _SESSION_LOCK:
            _SESSION.clear()
            _SESSION.update(
                {
                    "video_id": inp.video_id,
                    "position": max(0.0, float(inp.position or 0.0)),
                    "duration": float(inp.duration or 0.0),
                    "state": state_value,
                    "monotonic": time.monotonic(),
                    "updated_at": time.time(),
                }
            )
        return _session_payload()

    @router.get("/session")
    def read_session():
        return _session_payload()

    return router
