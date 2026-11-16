"""Lyrics providers mirrored from Limusic.

Order matches Limusic's default: Limusic, Boidu, Unison, LyricsPlus, LRCLIB,
YouTube Music, Netease, QQ Music and Kugou. Every provider is best-effort: a
failure or a missing song simply falls through to the next source.
"""

import base64
import html
import json
import re
from typing import Any, Callable, Optional

import requests

UA = "Lirify v1.0 (https://github.com/SimoHypers/limusic)"
TIMEOUT = 8


def _headers(referer: Optional[str] = None) -> dict:
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    return h


def _lrc_time(ms: float) -> str:
    seconds = max(ms, 0.0) / 1000.0
    return f"[{int(seconds // 60):02d}:{seconds % 60:05.2f}]"


def _ttml_seconds(value: str) -> Optional[float]:
    value = (value or "").strip()
    if not value:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", value)
    if not m:
        return None
    h, mnt, sec = m.groups()
    return (int(h or 0) * 3600) + (int(mnt) * 60) + float(sec)


def lyrics_to_text(raw: Any) -> str:
    """Turn provider output (LRC, TTML/AAML, KPOE JSON) into readable lyrics."""
    if raw is None:
        return ""
    if isinstance(raw, (list, dict)):
        data = raw
        text = ""
    else:
        text = str(raw).strip()
        if not text:
            return ""
        data = None
        if text[:1] in "[{":
            try:
                data = json.loads(text)
            except Exception:
                data = None

    if data is not None:
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("lyrics") or data.get("lines") or data.get("element")
            if not items:
                inner = data.get("data")
                if isinstance(inner, dict):
                    items = inner.get("lyrics") or inner.get("lines") or inner.get("element")
        else:
            items = None
        if isinstance(items, list):
            out = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                line = str(item.get("text") or item.get("words") or item.get("line") or "").strip()
                if not line:
                    continue
                stamp = item.get("time_ms")
                if stamp is None:
                    stamp = item.get("timeMs")
                if stamp is None:
                    stamp = item.get("time")
                if stamp is None:
                    stamp = item.get("startTime")
                if stamp is None:
                    stamp = item.get("start")
                if isinstance(stamp, (int, float)):
                    out.append(_lrc_time(float(stamp)) + line)
                else:
                    out.append(line)
            if out:
                return "\n".join(out)
        if isinstance(data, str):
            text = data

    raw_text = text or (json.dumps(data, ensure_ascii=False) if data is not None else "")
    stripped = raw_text.lstrip()
    if stripped.startswith("<"):
        out = []
        for attrs, inner in re.findall(r"<p\b([^>]*)>(.*?)</p>", raw_text, flags=re.S | re.I):
            line = re.sub(r"<[^>]+>", "", inner)
            line = html.unescape(line).strip()
            if not line:
                continue
            begin = re.search(r'begin\s*=\s*"([^"]+)"', attrs)
            stamp = _ttml_seconds(begin.group(1)) if begin else None
            out.append((_lrc_time(stamp * 1000) if stamp is not None else "") + line)
        if out:
            return "\n".join(out)
        return html.unescape(re.sub(r"<[^>]+>", " ", raw_text)).strip()

    return raw_text.strip()


def _first_line(raw: Any) -> str:
    return lyrics_to_text(raw)


def _limusic(track: str, artist: str, video_id: str, **_: Any) -> Optional[str]:
    if not video_id:
        return None
    r = requests.get(
        f"https://lyrics.limusic.app/v1/lyrics/{video_id}",
        headers=_headers(),
        timeout=6,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return json.dumps(r.json().get("lines") or [], ensure_ascii=False)


def _boidu(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    params = {"s": track, "a": artist}
    if duration:
        params["d"] = str(int(round(duration)))
    if album:
        params["al"] = album
    r = requests.get(
        "https://lyrics-api.boidu.dev/getLyrics",
        params=params,
        headers=_headers(),
        timeout=TIMEOUT,
    )
    if r.status_code in (401, 404):
        return None
    r.raise_for_status()
    data = r.json()
    for key in ("ttml", "syncedLyrics", "lyrics", "lrc"):
        raw = data.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw
        if isinstance(raw, (list, dict)):
            return json.dumps(raw, ensure_ascii=False)
    return None


def _unison(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    params = {"v": video_id} if video_id else {"song": track, "artist": artist}
    if not video_id and duration:
        params["duration"] = str(int(round(duration)))
    r = requests.get(
        "https://unison.betterlyrics.org/lyrics",
        params=params,
        headers=_headers(),
        timeout=TIMEOUT,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json().get("data") or {}
    raw = data.get("lyrics")
    return raw if raw else None


def _lyricsplus(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    params = {"title": re.sub(r"\s*[\(\[].*?[\)\]]", "", track).strip() or track, "artist": artist}
    if album:
        params["album"] = album
    if duration:
        params["duration"] = str(int(round(duration)))
    r = requests.get(
        "https://lyricsplus.binimum.org/v2/lyrics/get",
        params=params,
        headers=_headers(),
        timeout=TIMEOUT,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return json.dumps(data, ensure_ascii=False)


def _lrclib(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    params = {"track_name": track, "artist_name": artist}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = str(int(round(duration)))
    r = requests.get(
        "https://lrclib.net/api/get", params=params, headers=_headers(), timeout=TIMEOUT
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return data.get("syncedLyrics") or data.get("plainLyrics")


def _lrclib_search(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    r = requests.get(
        "https://lrclib.net/api/search",
        params={"q": f"{track} {artist}"},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    for item in r.json():
        raw = item.get("syncedLyrics") or item.get("plainLyrics")
        if raw:
            return raw
    return None


def _youtube(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    if not video_id:
        return None
    try:
        from ytmusicapi import YTMusic

        yt = YTMusic()
        watch = yt.get_watch_playlist(videoId=video_id, limit=1)
        browse_id = watch.get("lyrics")
        if not browse_id:
            return None
        result = yt.get_lyrics(browse_id)
        return result.get("lyrics")
    except Exception:
        return None


def _netease(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    headers = _headers("https://music.163.com/")
    r = requests.post(
        "https://music.163.com/api/search/get",
        data={"s": f"{track} {artist}", "type": "1", "limit": "5", "offset": "0"},
        headers=headers,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    songs = (r.json().get("result") or {}).get("songs") or []
    if not songs:
        return None
    chosen = songs[0]
    if duration:
        within = [
            s for s in songs
            if isinstance(s.get("duration"), (int, float))
            and abs(s["duration"] / 1000 - duration) <= 5
        ]
        if within:
            chosen = min(within, key=lambda s: abs(s["duration"] / 1000 - duration))
    song_id = chosen.get("id")
    if not song_id:
        return None
    lyric = requests.get(
        "https://music.163.com/api/song/lyric",
        params={"id": song_id, "lv": 1, "kv": 1, "tv": -1},
        headers=headers,
        timeout=TIMEOUT,
    )
    lyric.raise_for_status()
    return (lyric.json().get("lrc") or {}).get("lyric")


def _qq(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    headers = _headers("https://y.qq.com/")
    found = requests.get(
        "https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg",
        params={"format": "json", "key": f"{track} {artist}"},
        headers=headers,
        timeout=TIMEOUT,
    ).json()
    mids = [
        s.get("mid")
        for s in ((found.get("data") or {}).get("song") or {}).get("itemlist") or []
        if s.get("mid")
    ]
    if not mids:
        return None
    detail = requests.get(
        "https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg",
        params={"format": "json", "songmid": ",".join(mids)},
        headers=headers,
        timeout=TIMEOUT,
    ).json()
    songs = detail.get("data") or []
    if not isinstance(songs, list):
        return None
    chosen = songs[0] if songs else None
    if chosen and duration:
        within = [
            s for s in songs
            if isinstance(s.get("interval"), (int, float))
            and abs(s["interval"] - duration) <= 5
        ]
        if within:
            chosen = min(within, key=lambda s: abs(s["interval"] - duration))
    mid = (chosen or {}).get("mid")
    if not mid:
        return None
    lyric = requests.get(
        "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
        params={"songmid": mid, "format": "json", "nobase64": "1"},
        headers=headers,
        timeout=TIMEOUT,
    ).json()
    raw = lyric.get("lyric") or ""
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        if decoded.strip():
            raw = decoded
    except Exception:
        pass
    return raw or None


def _kugou(
    track: str, artist: str, video_id: str, album: Optional[str] = None,
    duration: Optional[float] = None, **_: Any,
) -> Optional[str]:
    search = requests.get(
        "https://songsearch.kugou.com/song_search_v2",
        params={"keyword": f"{track} {artist}", "page": 1, "pagesize": 5},
        headers=_headers(),
        timeout=TIMEOUT,
    ).json()
    songs = ((search.get("data") or {}).get("lists")) or []
    if not songs:
        return None
    chosen = songs[0]
    if duration:
        within = [
            s for s in songs
            if isinstance(s.get("Duration"), (int, float))
            and abs(s["Duration"] - duration) <= 5
        ]
        if within:
            chosen = min(within, key=lambda s: abs(s["Duration"] - duration))
    file_hash = chosen.get("FileHash")
    if not file_hash:
        return None
    krc = requests.get(
        "https://krcs.kugou.com/search",
        params={"ver": 1, "man": "yes", "client": "mobi", "hash": file_hash},
        headers=_headers(),
        timeout=TIMEOUT,
    ).json()
    candidate = ((krc.get("candidates") or [None])[0]) or {}
    cid, key = candidate.get("id"), candidate.get("accesskey")
    if not cid or not key:
        return None
    dl = requests.get(
        "https://lyrics.kugou.com/download",
        params={"ver": 1, "client": "pc", "id": cid, "accesskey": key, "fmt": "lrc"},
        headers=_headers(),
        timeout=TIMEOUT,
    ).json()
    content = dl.get("content") or ""
    try:
        return base64.b64decode(content).decode("utf-8")
    except Exception:
        return None


PROVIDERS: list[tuple[str, Callable[..., Optional[str]]]] = [
    ("limusic", _limusic),
    ("boidu", _boidu),
    ("unison", _unison),
    ("lyricsplus", _lyricsplus),
    ("lrclib", _lrclib),
    ("lrclib_search", _lrclib_search),
    ("youtube", _youtube),
    ("netease", _netease),
    ("qq", _qq),
    ("kugou", _kugou),
]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def probe_instrumental(
    track: str, artist: str, duration: Optional[float] = None
) -> bool:
    """Confirm a track exists in a catalogue but carries no lyrics at all.

    Used only after every lyrics provider has already returned nothing. An exact
    Netease catalogue hit (title, artist and length) whose lyric document is
    empty is treated as instrumental/lyric-less. LRCLIB's explicit
    ``instrumental`` flag is also accepted.
    """
    want_title, want_artist = _norm(track), _norm(artist)
    if not want_title:
        return False

    try:
        r = requests.post(
            "https://music.163.com/api/search/get",
            data={"s": f"{track} {artist}", "type": "1", "limit": "10", "offset": "0"},
            headers=_headers("https://music.163.com/"),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        songs = (r.json().get("result") or {}).get("songs") or []
        for song in songs:
            title = _norm(song.get("name", ""))
            artists = _norm(" ".join(a.get("name", "") for a in song.get("artists") or []))
            length = song.get("duration")
            if title != want_title:
                continue
            if want_artist and want_artist not in artists and artists not in want_artist:
                continue
            if duration and isinstance(length, (int, float)):
                if abs(length / 1000 - duration) > 5:
                    continue
            lyric = requests.get(
                "https://music.163.com/api/song/lyric",
                params={"id": song.get("id"), "lv": 1, "kv": 1, "tv": -1},
                headers=_headers("https://music.163.com/"),
                timeout=TIMEOUT,
            )
            lyric.raise_for_status()
            lrc = (lyric.json().get("lrc") or {}).get("lyric") or ""
            return not lrc.strip()
    except Exception:
        pass

    try:
        r = requests.get(
            "https://lrclib.net/api/search",
            params={"q": f"{track} {artist}"},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for item in r.json():
            if item.get("instrumental") and _norm(item.get("trackName", "")) == want_title:
                return True
    except Exception:
        pass
    return False


def fetch_lyrics(
    track: str,
    artist: str,
    video_id: str = "",
    album: Optional[str] = None,
    duration: Optional[float] = None,
) -> tuple[str, Optional[str]]:
    """Try every Limusic source in order; return (lyrics, provider id)."""
    for name, provider in PROVIDERS:
        try:
            raw = provider(
                track=track,
                artist=artist,
                video_id=video_id,
                album=album,
                duration=duration,
            )
        except Exception:
            continue
        text = lyrics_to_text(raw)
        if text and text.strip():
            return text.strip(), name
    return "", None
