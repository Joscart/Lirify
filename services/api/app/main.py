"""Lirify core engine.

Stateless by design. MongoDB Atlas owns tracks, jobs, stashes and the player
caches; Qdrant Cloud owns the lyric embeddings. Cloud Run can recycle this
container at any moment, so nothing in this module writes to local disk: the
in-process index is a rebuildable cache, never the source of truth.
"""

import asyncio
import json
import math
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import numpy as np
import requests
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    from langdetect import DetectorFactory

    DetectorFactory.seed = 0
except Exception:
    pass

from lyrics_sources import PROVIDERS as LYRICS_PROVIDERS
from lyrics_sources import fetch_lyrics, lyrics_to_text, probe_instrumental
from bot_api import TERMINAL_ERRORS, build_bot_router, classify_playlist_error
from store import get_store, new_job_id
from vector import embed_lyrics, get_vector_store

WEIGHTS = {"name": 0.10, "artist": 0.05, "lang": 0.05, "lyrics": 0.8}

# video id -> YouTube duration in seconds, filled while extracting ids.
DURATIONS: Dict[str, float] = {}

STORE = get_store()
VECTORS = get_vector_store()

MAX_ATTEMPTS = int(os.environ.get("MAX_JOB_ATTEMPTS", "8"))
# Cloud Run free tier gives this container 512 MiB. The in-process TF-IDF index
# costs O(vocabulary x songs) plus O(songs^2) matrices; refuse to commit past the
# guard instead of being OOM-killed mid-batch. -1 disables the guard (local only).
MAX_INDEXED_SONGS = int(os.environ.get("MAX_INDEXED_SONGS", "1000"))
RETRY_INTERVAL = int(os.environ.get("RETRY_INTERVAL_SECONDS", "300"))
QUEUE_DIRTY = False

# Two-stage pipeline: playlist scrapers feed the index stash, a separate worker
# computes matrices and commits the stash to the live index.
PLAYLIST_QUEUE: asyncio.Queue = asyncio.Queue()
MATRIX_QUEUE: asyncio.Queue = asyncio.Queue()
COMMIT_LOCK = asyncio.Lock()
WORKERS: List[asyncio.Task] = []
GRPC_SERVER = None
GRPC_ERROR = ""

app = FastAPI(title="Lirify API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public REST surface is readable by anyone (the index is public data) but rate
# limited per client IP. Writes go through the bearer-protected bot API, which has
# its own quota. Both limits are disabled with 0 (local compose).
PUBLIC_RATE_LIMIT = int(os.environ.get("PUBLIC_RATE_LIMIT_PER_MINUTE", "120"))
PUBLIC_RATE_WINDOW = 60
RATE_EXEMPT = {
    "/health",
    "/healthz",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class IpRateLimiter:
    """Per-IP fixed window. In-process on purpose: the free tier runs one instance,
    so this costs no database round-trip on the hot read path."""

    def __init__(self, limit: int, window: int) -> None:
        self.limit = limit
        self.window = window
        self.buckets: Dict[str, tuple] = {}
        self.lock = threading.Lock()

    def hit(self, key: str) -> tuple:
        if self.limit <= 0:
            return True, 0, 0
        now = time.time()
        with self.lock:
            count, reset = self.buckets.get(key, (0, now + self.window))
            if reset <= now:
                count, reset = 0, now + self.window
            count += 1
            self.buckets[key] = (count, reset)
            if len(self.buckets) > 10_000:
                for stale in [k for k, (_, r) in self.buckets.items() if r <= now][:5000]:
                    self.buckets.pop(stale, None)
        return count <= self.limit, count, max(0, int(reset - now))


PUBLIC_LIMITER = IpRateLimiter(PUBLIC_RATE_LIMIT, PUBLIC_RATE_WINDOW)


def _client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def public_rate_limit(request, call_next):
    path = request.url.path
    if PUBLIC_LIMITER.limit <= 0 or path in RATE_EXEMPT or path.startswith("/api/v1/bot"):
        return await call_next(request)
    allowed, count, reset = PUBLIC_LIMITER.hit(_client_ip(request))
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "detail": {
                    "code": "rate_limited",
                    "message": f"Limit is {PUBLIC_LIMITER.limit} requests per {PUBLIC_LIMITER.window}s per IP",
                    "retry_after_seconds": reset,
                }
            },
            headers={"Retry-After": str(reset)},
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(PUBLIC_LIMITER.limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, PUBLIC_LIMITER.limit - count))
    return response

STATE: Dict[str, Any] = {
    "songs": [],
    "ids": [],
    "index": {},
    "vocab": [],
    "doc_freq": None,
    "tfidf": None,
    "matrices": {},
    "build": {},
    "vectors": None,
}


class UrlIn(BaseModel):
    url: str
    limit: Optional[int] = None


class QueueIn(BaseModel):
    url: Optional[str] = None
    urls: List[str] = []
    limit: Optional[int] = None
    source: Optional[str] = None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "to",
    "in", "on", "at", "by", "for", "with", "about", "against", "between",
    "into", "through", "during", "before", "after", "above", "below", "from",
    "up", "down", "out", "off", "over", "under", "again", "further", "once",
    "here", "there", "when", "where", "why", "how", "all", "any", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "can", "will",
    "just", "should", "now", "i", "me", "my", "myself", "we", "our", "ours",
    "you", "your", "yours", "he", "him", "his", "she", "her", "hers", "it",
    "its", "they", "them", "their", "what", "which", "who", "whom", "this",
    "that", "these", "those", "am", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "doing", "would",
    "could", "ought", "im", "youre", "hes", "shes", "its", "were", "theyre",
    "ive", "youve", "weve", "theyve", "id", "youd", "hed", "shed", "wed",
    "theyd", "ill", "youll", "hell", "shell", "well", "theyll", "isnt",
    "arent", "wasnt", "werent", "havent", "hasnt", "hadnt", "doesnt",
    "dont", "didnt", "wont", "wouldnt", "shant", "shouldnt", "cant",
    "cannot", "couldnt", "mustnt", "lets", "thats", "whos", "whats",
    "heres", "theres", "whens", "wheres", "whys", "hows", "yall",
}

_SPANISH_STOP = {
    "a", "al", "algo", "algunas", "algunos", "ante", "antes", "como", "con",
    "contra", "cual", "cuando", "de", "del", "desde", "donde", "durante",
    "e", "el", "ella", "ellas", "ellos", "en", "entre", "era", "es", "esa",
    "esas", "ese", "eso", "esos", "esta", "estas", "este", "esto", "estos",
    "fue", "ha", "hasta", "hay", "la", "las", "le", "les", "lo", "los",
    "me", "mi", "mis", "mucho", "muy", "no", "nos", "o", "otra", "otro",
    "para", "pero", "poco", "por", "porque", "que", "quien", "se", "sin",
    "sobre", "su", "sus", "te", "tu", "tus", "un", "una", "uno", "y", "ya",
}

try:  # Snowball gives language-aware stemming without downloads.
    from nltk.stem.snowball import SnowballStemmer

    STEMMERS = {}
    for code, name in {
        "en": "english", "es": "spanish", "fr": "french", "de": "german",
        "it": "italian", "pt": "portuguese", "nl": "dutch", "ru": "russian",
    }.items():
        try:
            STEMMERS[code] = SnowballStemmer(name)
        except Exception:
            pass
except Exception:  # pragma: no cover
    STEMMERS = {}


def remove_special(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def normalize_name(text: str) -> str:
    return re.sub(r"\s+", " ", remove_special(text or ""))


def normalize_artist(text: str) -> str:
    text = re.sub(r"\s*-\s*topic$", "", (text or ""), flags=re.I)
    return re.sub(r"\s+", " ", remove_special(text))


def normalize_lang(text: str) -> str:
    return (text or "").strip().lower()


TIMESTAMP_RE = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\]")
LRC_META_RE = re.compile(r"^\[[A-Za-z]+:.*?\]$", re.M)
NON_LATIN_RE = re.compile(
    r"[\u0370-\u03ff\u0400-\u04ff\u0590-\u05ff\u0600-\u06ff"
    r"\u0900-\u097f\u0e00-\u0e7f\u3040-\u30ff\u3400-\u4dbf"
    r"\u4e00-\u9fff\uac00-\ud7af]"
)

# Only English and Spanish songs may enter the index.
ALLOWED_LANGUAGES = {"en", "es"}

ENGLISH_HINTS = {
    "the", "and", "you", "that", "this", "with", "have", "from", "your", "what",
    "when", "were", "there", "they", "will", "would", "could", "should", "about",
    "just", "like", "know", "want", "need", "love", "time", "heart", "night",
    "day", "life", "never", "again", "because", "through", "over", "into",
}

SPANISH_HINTS = {
    "el", "la", "los", "las", "de", "del", "que", "y", "en", "un", "una", "por",
    "para", "con", "sin", "mi", "tu", "su", "es", "son", "estoy", "estas", "esta",
    "como", "pero", "mas", "muy", "todo", "todos", "nada", "amor", "corazon",
    "vida", "noche", "dia", "siempre", "nunca", "quiero", "puedo", "tengo",
    "eres", "somos", "cuando", "donde", "porque", "hasta", "desde", "tiempo",
}


def normalize_lyrics(text: str, lang: str) -> List[str]:
    text = TIMESTAMP_RE.sub(" ", text or "")
    text = remove_special(text)
    stop = set(STOPWORDS)
    if lang == "es":
        stop |= _SPANISH_STOP
    stemmer = STEMMERS.get(lang)
    tokens = []
    for word in text.split():
        if word in stop or len(word) < 2:
            continue
        tokens.append(stemmer.stem(word) if stemmer else word)
    return tokens


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def extract_video_ids(url: str) -> List[str]:
    cmd = [
        "yt-dlp", "--flat-playlist", "--no-warnings",
        "--print", "%(id)s\t%(duration)s", url,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if out.returncode != 0 and not out.stdout.strip():
        raise HTTPException(400, f"yt-dlp failed: {out.stderr[-1000:]}")
    ids = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        vid = parts[0].strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            if len(parts) > 1:
                try:
                    DURATIONS[vid] = float(parts[1])
                except ValueError:
                    pass
            if vid not in ids:
                ids.append(vid)
    if not ids:
        raise HTTPException(400, "No video IDs found in that URL")
    return ids


def fetch_metadata(video_id: str) -> Dict[str, str]:
    try:
        r = requests.get(
            "https://noembed.com/embed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}"},
            timeout=15,
        )
        r.raise_for_status()
        d = r.json()
        return {"title": d.get("title", ""), "author": d.get("author_name", "")}
    except Exception:
        return {"title": "", "author": ""}


def parse_title(title: str, author: str):
    title = re.sub(r"\s*\((?:official\s*)?(?:lyric|lyrics|audio|video|music)\s*(?:video)?\)", "", title, flags=re.I)
    title = re.sub(r"\s*\[(?:official\s*)?(?:lyric|lyrics|audio|video|music)\s*(?:video)?\]", "", title, flags=re.I)
    if " - " in title:
        artist, track = title.split(" - ", 1)
    else:
        artist, track = author, title
    artist = re.sub(r"\s*-\s*topic$", "", artist or "", flags=re.I).strip()
    track = re.sub(r"\s*\((?:official\s*)?(?:lyric|lyrics|audio|video|music)[^)]*\)", "", track, flags=re.I).strip()
    return artist.strip(), track.strip()


def detect_language(text: str) -> str:
    """Detect language with an English/Spanish fallback pass.

    langdetect wins when it is confident. If it isn't, or it lands on a
    non-target language from very sparse lyric text, word hints are checked again
    before giving up. Anything that still is not en/es is returned as-is and is
    filtered out of the index later.
    """
    raw = TIMESTAMP_RE.sub(" ", text or "")
    raw = LRC_META_RE.sub(" ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)

    # Script veto: a lyric dominated by CJK/Cyrillic/Arabic/etc. is not en/es,
    # even if a few romanised words fool langdetect. Check before stripping
    # non-Latin characters below.
    non_latin = len(NON_LATIN_RE.findall(raw))
    if non_latin >= 10 and non_latin / max(len(raw), 1) >= 0.12:
        return "non-latin"

    plain = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ' ]", " ", raw)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) < 8:
        return "unknown"

    try:
        from langdetect import detect_langs

        ranked = detect_langs(plain)
    except Exception:
        ranked = []

    if ranked:
        top = ranked[0]
        if top.lang in ALLOWED_LANGUAGES:
            return top.lang
        if top.prob >= 0.90:
            return top.lang

    words = plain.lower().split()
    en_hits = sum(1 for w in words if w in ENGLISH_HINTS)
    es_hits = sum(1 for w in words if w in SPANISH_HINTS)
    accents = sum(1 for ch in plain if ch in "¿¡ñÑáéíóúÁÉÍÓÚüÜ")

    if es_hits or accents >= 2:
        if es_hits >= 2 and es_hits >= en_hits:
            return "es"
    if en_hits >= 2 and en_hits > es_hits:
        return "en"
    if ranked:
        return ranked[0].lang
    return "unknown"


def scrape_song(video_id: str) -> Dict[str, Any]:
    cached = load_cached_song(video_id)
    if cached:
        cached["language"] = detect_language(cached.get("lyrics", ""))
        return cached
    meta = fetch_metadata(video_id)
    artist, track = parse_title(meta["title"], meta["author"])
    lyrics, backend = fetch_lyrics(
        track, artist, video_id=video_id, duration=DURATIONS.get(video_id)
    )
    song = {
        "video_id": video_id,
        "title": meta["title"],
        "artist": artist,
        "track": track,
        "language": detect_language(lyrics),
        "lyrics": lyrics,
        "backend": backend,
    }
    if lyrics.strip():
        save_cached_song(song)
    return song


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def load_cached_song(video_id: str) -> Optional[Dict[str, Any]]:
    """Only successful lyric lookups are cached, so failures stay retryable."""
    return STORE.cache_get(video_id)


def save_cached_song(song: Dict[str, Any]) -> None:
    if not (song.get("lyrics") or "").strip():
        return
    STORE.cache_put(song)


def record_failed(song: Dict[str, Any], reason: str = "no lyrics") -> None:
    STORE.failed_record(song, reason, DURATIONS.get(song["video_id"]))


def resolve_failed(video_id: str) -> None:
    STORE.failed_resolve(video_id)


def flush_jobs() -> None:
    """Persist in-memory job progress so a cold start can resume and bots can poll."""
    global QUEUE_DIRTY
    try:
        for job in list(JOBS.values()):
            STORE.job_put(job)
    except Exception as exc:  # pragma: no cover - Atlas hiccup
        print(f"[lirify] job flush failed: {exc}", flush=True)
        return
    QUEUE_DIRTY = False


def save_queue_state() -> None:
    flush_jobs()


def build_stash_index(songs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Inverted index for a batch only; document ids are local to the batch."""
    index: Dict[str, Dict[str, List[int]]] = {}
    tokens = 0
    for doc, song in enumerate(songs):
        words = normalize_lyrics(song["lyrics"], song["language"])
        tokens += len(words)
        for pos, word in enumerate(words):
            index.setdefault(word, {}).setdefault(str(doc), []).append(pos + 1)
    return {"index": index, "terms": len(index), "tokens": tokens, "docs": len(songs)}


def save_stash(batch_id: str, songs: List[Dict[str, Any]], stash: Dict[str, Any]) -> str:
    STORE.stash_put(batch_id, songs, stash)
    return f"mongodb://{STORE.backend}/stashes/{batch_id}"


def remove_stash(batch_id: str) -> None:
    STORE.stash_delete(batch_id)


def build_index(songs: List[Dict[str, Any]]):
    names = [normalize_name(s["track"]) for s in songs]
    artists = [normalize_artist(s["artist"]) for s in songs]
    langs = [normalize_lang(s["language"]) for s in songs]
    tokens = [normalize_lyrics(s["lyrics"], s["language"]) for s in songs]

    index: Dict[str, Dict[str, List[int]]] = {}
    for doc, words in enumerate(tokens):
        for pos, word in enumerate(words):
            index.setdefault(word, {}).setdefault(str(doc), []).append(pos + 1)

    vocab = sorted(index)
    # One float32 matrix is enough: term counts are converted to TF in place, then
    # scaled by IDF in place, then normalised in place. The previous version held
    # counts + tf + tfidf + unit at once, which cost ~4x the memory and pushed a
    # 512 MiB Cloud Run container into OOM territory at ~1000 songs.
    tfidf = np.zeros((len(vocab), len(songs)), dtype=np.float32)
    for row, term in enumerate(vocab):
        for doc, positions in index[term].items():
            tfidf[row, int(doc)] = len(positions)

    positive = tfidf > 0
    doc_freq = positive.sum(axis=1).astype(np.int32)
    docs = max(len(songs), 1)
    idf = np.log10(docs / np.where(doc_freq == 0, 1, doc_freq)).astype(np.float32)

    # log-normalised TF, in place
    tfidf[positive] = np.log10(tfidf[positive]) + 1.0
    # TF-IDF, in place
    tfidf *= idf[:, None]
    # L2 normalisation, in place
    norms = np.linalg.norm(tfidf, axis=0)
    norms[norms == 0] = 1.0
    tfidf /= norms
    tfidf_unit = tfidf
    counts = doc_freq  # kept in the tuple slot for callers; vocab-sized, not vocab x songs

    n = len(songs)

    def jaccard(a: str, b: str) -> float:
        sa, sb = set(a.split()), set(b.split())
        if not sa and not sb:
            return 1.0
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    m_name = np.zeros((n, n), dtype=np.float32)
    m_artist = np.zeros((n, n), dtype=np.float32)
    m_lang = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(n):
            m_name[i, j] = jaccard(names[i], names[j])
            m_artist[i, j] = jaccard(artists[i], artists[j])
            m_lang[i, j] = (
                1.0 if langs[i] == langs[j] and langs[i] not in ("", "unknown") else 0.0
            )

    m_lyrics = tfidf_unit.T @ tfidf_unit
    unified = (
        WEIGHTS["name"] * m_name
        + WEIGHTS["artist"] * m_artist
        + WEIGHTS["lang"] * m_lang
        + WEIGHTS["lyrics"] * m_lyrics
    )
    peak = unified.max() if unified.size else 0.0
    if peak > 0:
        unified = unified / peak

    matrices = {
        "name": m_name,
        "artist": m_artist,
        "language": m_lang,
        "lyrics": m_lyrics,
        "unified": unified,
    }

    build = {
        "weights": WEIGHTS,
        "vocabulary_size": len(vocab),
        "inverted_terms": len(index),
        "songs_indexed": n,
        "lyrics_tokens": int(sum(len(t) for t in tokens)),
        "languages": {},
        "backends": {},
    }
    for s in songs:
        build["languages"][s["language"]] = build["languages"].get(s["language"], 0) + 1
        key = s["backend"] or "none"
        build["backends"][key] = build["backends"].get(key, 0) + 1

    return index, vocab, counts, tfidf_unit, names, artists, langs, tokens, matrices, build


def persist(only: Optional[List[Dict[str, Any]]] = None) -> None:
    """Commit the live index to MongoDB Atlas and Qdrant Cloud.

    ``only`` limits the writes to a freshly committed batch; stats and the
    in-process ``STATE`` always describe the whole index.
    """
    songs = STATE["songs"] if only is None else only
    build = STATE.get("build") or {}
    written = STORE.commit_songs(songs, build)
    STORE.stats_put(build)
    if VECTORS.backend != "none":
        VECTORS.upsert(songs)
    print(f"[lirify] persisted {written} song upserts ({STORE.backend})", flush=True)


def build_vectors(songs: List[Dict[str, Any]]):
    if not songs:
        return None
    return np.array(
        [embed_lyrics(s.get("lyrics", "")) for s in songs], dtype=np.float32
    )


def load_state() -> None:
    """Hydrate the in-process index from MongoDB. Runs once per cold start."""
    load_limit = MAX_INDEXED_SONGS if MAX_INDEXED_SONGS >= 0 else None
    try:
        stored = STORE.load_songs(limit=load_limit)
    except Exception as exc:  # pragma: no cover - Atlas unreachable
        print(f"[lirify] could not load songs from {STORE.backend}: {exc}", flush=True)
        return
    try:
        for key, value in STORE.durations_all().items():
            DURATIONS[key] = float(value)
    except Exception:
        pass
    if not stored:
        return
    songs = []
    for s in stored:
        lyrics = s.get("lyrics", "")
        backend = s.get("backend")
        # Only songs with real lyrics are ever committed to the live index.
        if not lyrics.strip() or backend == "instrumental":
            continue
        language = detect_language(lyrics)
        if language not in ALLOWED_LANGUAGES:
            continue
        songs.append(
            {
                "video_id": s.get("video_id", ""),
                "track": s.get("track") or s.get("title", ""),
                "title": s.get("title", "") or s.get("track", ""),
                "artist": s.get("artist", ""),
                "language": language,
                "lyrics": lyrics,
                "backend": backend,
            }
        )
    if not songs:
        return
    if load_limit is not None and len(stored) > len(songs):
        print(
            f"[lirify] loaded {len(songs)} of {len(stored)} songs "
            f"(MAX_INDEXED_SONGS={MAX_INDEXED_SONGS})",
            flush=True,
        )
    index, vocab, counts, tfidf, names, artists, langs, tokens, matrices, build = build_index(songs)
    STATE.update(
        songs=songs,
        ids=[s["video_id"] for s in songs],
        index=index,
        vocab=vocab,
        doc_freq=counts,
        tfidf=tfidf,
        matrices=matrices,
        build=build,
        names=names,
        artists=artists,
        langs=langs,
        tokens=tokens,
        vectors=build_vectors(songs) if VECTORS.backend == "none" else None,
    )
    try:
        STORE.prune_songs([s["video_id"] for s in songs])
        STORE.stats_put(build)
    except Exception as exc:  # pragma: no cover
        print(f"[lirify] index reconciliation failed: {exc}", flush=True)
    print(f"[lirify] loaded {len(songs)} songs from {STORE.backend}", flush=True)


load_state()


# ---------------------------------------------------------------------------
# Live progress over WebSocket
# ---------------------------------------------------------------------------

class ProgressHub:
    """Broadcasts scraping/indexing progress to every connected client."""

    def __init__(self) -> None:
        self.clients = set()
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self.lock:
            self.clients.discard(ws)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        async with self.lock:
            clients = list(self.clients)
        dead = []
        for ws in clients:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


hub = ProgressHub()
JOBS: Dict[str, Dict[str, Any]] = {}


async def _emit(job_id: str, event: str, **fields: Any) -> None:
    global QUEUE_DIRTY
    payload = {"event": event, "job_id": job_id, "ts": time.time()}
    payload.update(fields)
    if job_id in JOBS:
        JOBS[job_id]["last_event"] = event
        JOBS[job_id]["updated_at"] = time.time()
    QUEUE_DIRTY = True
    await hub.broadcast(payload)


async def run_extract_job(job_id: str, url: str, limit: Optional[int]) -> None:
    JOBS[job_id] = {
        "job_id": job_id,
        "action": "extract",
        "url": url,
        "status": "running",
        "created_at": time.time(),
    }
    await _emit(job_id, "start", action="extract", url=url)
    await _emit(job_id, "status", stage="extract", message="Extracting video IDs with yt-dlp")
    try:
        ids = await asyncio.to_thread(extract_video_ids, url)
        if limit:
            ids = ids[:limit]
        # Extraction is a preview; nothing is committed and no ids are persisted.
        await _emit(job_id, "extracted", count=len(ids), ids=ids)
        JOBS[job_id].update(status="done", count=len(ids))
        await _emit(job_id, "done", action="extract", count=len(ids))
    except Exception as exc:
        JOBS[job_id].update(status="error", error=str(exc))
        await _emit(job_id, "error", message=str(exc))


async def stage_index(job_id: str, url: str, limit: Optional[int]):
    """Stage 1: extract, scrape lyrics, and stash an inverted index for the batch."""
    JOBS.setdefault(
        job_id, {"job_id": job_id, "action": "index", "url": url, "created_at": time.time()}
    )
    JOBS[job_id].update(status="indexing", stage="extract", error=None)
    await _emit(job_id, "status", stage="extract", message="Extracting video IDs with yt-dlp")
    try:
        ids = await asyncio.to_thread(extract_video_ids, url)
    except Exception as exc:
        failure = classify_playlist_error(str(exc))
        JOBS[job_id].update(
            status="error", error=str(exc), error_code=failure["code"]
        )
        await _emit(job_id, "error", message=str(exc), code=failure["code"], hint=failure["hint"])
        return None
    if limit:
        ids = ids[:limit]
    await _emit(job_id, "extracted", count=len(ids), ids=ids)
    await _emit(
        job_id,
        "status",
        stage="scrape",
        message=f"Scraping lyrics for {len(ids)} songs",
        total=len(ids),
    )

    songs: List[Dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        future_to_id = {loop.run_in_executor(pool, scrape_song, vid): vid for vid in ids}
        pending = set(future_to_id)
        while pending:
            completed, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for future in completed:
                done += 1
                video_id = future_to_id[future]
                try:
                    song = future.result()
                except Exception as exc:
                    await _emit(
                        job_id,
                        "song_error",
                        index=done,
                        total=len(ids),
                        video_id=video_id,
                        message=str(exc),
                    )
                    continue
                songs.append(song)
                await _emit(
                    job_id,
                    "song",
                    index=done,
                    total=len(ids),
                    progress=round(done / max(len(ids), 1), 4),
                    video_id=song["video_id"],
                    title=song["track"],
                    artist=song["artist"],
                    language=song["language"],
                    backend=song["backend"],
                    has_lyrics=bool(song["lyrics"].strip()),
                    indexed=len(songs),
                )

    if not songs:
        JOBS[job_id].update(status="error", error="No songs could be indexed")
        await _emit(job_id, "error", message="No songs could be indexed")
        return None

    # Providers rate-limit under parallel load, so give unresolved songs one
    # sequential second chance before filtering them out.
    unresolved = [s for s in songs if not s["lyrics"].strip()]
    if unresolved:
        await _emit(
            job_id,
            "status",
            stage="retry",
            message=f"Retrying {len(unresolved)} songs without lyrics",
            total=len(unresolved),
        )
        for position, song in enumerate(unresolved[:50], start=1):
            await asyncio.sleep(0.4)
            text, backend = await asyncio.to_thread(
                fetch_lyrics,
                song["track"],
                song["artist"],
                song["video_id"],
                None,
                DURATIONS.get(song["video_id"]),
            )
            if text:
                song["lyrics"] = text
                song["backend"] = backend
                song["language"] = detect_language(text)
                await _emit(
                    job_id,
                    "song_retry",
                    index=position,
                    total=len(unresolved),
                    video_id=song["video_id"],
                    title=song["track"],
                    artist=song["artist"],
                    language=song["language"],
                    backend=backend,
                    has_lyrics=True,
                )

    # Commit rules: lyrics must exist and the language must be English or Spanish.
    with_lyrics = [s for s in songs if s["lyrics"].strip()]
    no_lyrics = [s for s in songs if not s["lyrics"].strip()]
    eligible = [s for s in with_lyrics if s["language"] in ALLOWED_LANGUAGES]
    language_skipped = [
        s for s in with_lyrics if s["language"] not in ALLOWED_LANGUAGES
    ]
    for song in no_lyrics:
        await asyncio.to_thread(record_failed, song)
    for song in eligible:
        await asyncio.to_thread(resolve_failed, song["video_id"])
    skipped = no_lyrics + language_skipped
    await _emit(
        job_id,
        "filtered",
        kept=len(eligible),
        skipped=len(skipped),
        no_lyrics=len(no_lyrics),
        language_skipped=len(language_skipped),
        allowed_languages=sorted(ALLOWED_LANGUAGES),
        skipped_songs=[
            {
                "video_id": s["video_id"],
                "title": s["track"],
                "artist": s["artist"],
                "language": s.get("language", "unknown"),
            }
            for s in skipped[:50]
        ],
    )
    if not eligible:
        reason = "no lyrics" if no_lyrics else "language not en/es"
        JOBS[job_id].update(status="skipped", stage="filter", reason=reason)
        await _emit(
            job_id,
            "skipped",
            reason=f"No songs passed the filter ({reason})",
            skipped=len(skipped),
            language_skipped=len(language_skipped),
        )
        return None

    await _emit(
        job_id,
        "status",
        stage="index_stash",
        message=f"Building stashed inverted index for {len(eligible)} songs",
        total=len(eligible),
    )
    stash = await asyncio.to_thread(build_stash_index, eligible)
    path = await asyncio.to_thread(save_stash, job_id, eligible, stash)
    JOBS[job_id].update(
        status="matrix_pending",
        stage="index_stash",
        batch_id=job_id,
        stash_path=path,
        stash_docs=stash["docs"],
        stash_terms=stash["terms"],
        stash_tokens=stash["tokens"],
    )
    await _emit(
        job_id,
        "stashed",
        batch_id=job_id,
        docs=stash["docs"],
        terms=stash["terms"],
        tokens=stash["tokens"],
        path=path,
    )
    return {"job_id": job_id, "songs": eligible, "stash": stash, "path": path}


async def stage_matrix(batch: Dict[str, Any]) -> None:
    """Stage 2: compute matrices from commit + stash, then atomically commit."""
    job_id = batch["job_id"]
    try:
        await _emit(
            job_id,
            "status",
            stage="matrix",
            message="Calculating similarity matrices",
        )
        async with COMMIT_LOCK:
            previous = STATE["songs"]
            combined: List[Dict[str, Any]] = []
            seen = set()
            for song in previous + batch["songs"]:
                video_id = song.get("video_id")
                if not video_id or video_id in seen:
                    continue
                if not song.get("lyrics", "").strip():
                    continue
                language = detect_language(song["lyrics"])
                song["language"] = language
                if language not in ALLOWED_LANGUAGES:
                    continue
                seen.add(video_id)
                combined.append(song)
            added = max(len(combined) - len(previous), 0)

            if added == 0:
                await asyncio.to_thread(remove_stash, job_id)
                JOBS[job_id].update(status="skipped", stage="matrix", reason="duplicate")
                await _emit(
                    job_id,
                    "skipped",
                    reason="No new songs with lyrics (already indexed)",
                )
                return

            if MAX_INDEXED_SONGS >= 0 and len(combined) > MAX_INDEXED_SONGS:
                await asyncio.to_thread(remove_stash, job_id)
                JOBS[job_id].update(
                    status="error", stage="matrix", error="index capacity guard"
                )
                await _emit(
                    job_id,
                    "error",
                    message=(
                        f"Index capacity guard: {len(combined)} songs would exceed "
                        f"MAX_INDEXED_SONGS={MAX_INDEXED_SONGS}. Nothing was committed."
                    ),
                )
                return

            index_data, vocab, counts, tfidf, names, artists, langs, tokens, matrices, build = await asyncio.to_thread(
                build_index, combined
            )
            STATE.update(
                songs=combined,
                ids=[s["video_id"] for s in combined],
                index=index_data,
                vocab=vocab,
                doc_freq=counts,
                tfidf=tfidf,
                matrices=matrices,
                build=build,
                names=names,
                artists=artists,
                langs=langs,
                tokens=tokens,
                vectors=(
                    await asyncio.to_thread(build_vectors, combined)
                    if VECTORS.backend == "none"
                    else None
                ),
            )
            # Only the freshly committed batch reaches Atlas/Qdrant; the stats
            # document always describes the whole index.
            await asyncio.to_thread(persist, batch["songs"])
            await asyncio.to_thread(remove_stash, job_id)

        JOBS[job_id].update(status="committed", stage="commit", stats=build, added=added)
        await _emit(
            job_id,
            "status",
            stage="commit",
            message=f"Committed {added} songs",
            added=added,
            stats=build,
        )
        await _emit(
            job_id,
            "done",
            action="index",
            added=added,
            stats=build,
        )
    except Exception as exc:
        JOBS[job_id].update(status="error", stage="matrix", error=str(exc))
        await _emit(job_id, "error", message=f"Matrix/commit failed: {exc}")


async def run_index_job(job_id: str, url: str, limit: Optional[int]) -> None:
    """Synchronous single-playlist path: index now, then commit immediately."""
    JOBS[job_id] = {
        "job_id": job_id,
        "action": "index",
        "url": url,
        "status": "running",
        "created_at": time.time(),
    }
    await _emit(job_id, "start", action="index", url=url)
    batch = await stage_index(job_id, url, limit)
    if batch:
        await stage_matrix(batch)


async def enqueue_playlist(url: str, limit: Optional[int] = None, source: str = "manual") -> str:
    job_id = new_job_id("job")
    JOBS[job_id] = {
        "job_id": job_id,
        "action": "queue",
        "url": url,
        "limit": limit,
        "status": "queued",
        "stage": "queued",
        "source": source,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    await asyncio.to_thread(STORE.job_put, JOBS[job_id])
    await PLAYLIST_QUEUE.put({"job_id": job_id, "url": url, "limit": limit, "source": source})
    await _emit(job_id, "queued", url=url, source=source, queue_size=PLAYLIST_QUEUE.qsize())
    return job_id


async def _finish_failed_playlist(job_id: str, reason: str) -> None:
    """End a failed playlist job and hand the retry decision to the agent.

    The server deliberately does not schedule scrape retries. YouTube's anti-bot
    challenge is time- and egress-dependent, and a retry loop here would burn the
    free-tier quota without changing the outcome. Agents resubmit through the bot
    API after a randomised delay (see skills/lirify-playlist-indexer).
    """
    job = JOBS.setdefault(job_id, {"job_id": job_id, "created_at": time.time()})
    failure = classify_playlist_error(reason)
    job.update(
        status="error",
        stage="gave_up",
        error=reason,
        error_code=failure["code"],
        retry_mode=failure.get("retry_mode"),
        updated_at=time.time(),
    )
    await _emit(
        job_id,
        "gave_up",
        attempts=int(job.get("attempts", 0)),
        code=failure["code"],
        retry_mode=failure.get("retry_mode"),
        retryable=failure.get("retryable"),
        retry_window_seconds=failure.get("retry_window_seconds"),
        message=(
            f"{failure['hint']} Resubmit through the bot API if the agent decides to retry."
            if failure.get("retryable")
            else failure["hint"]
        ),
    )


async def index_worker() -> None:
    """Scrapes queued playlists and stashes their inverted indexes."""
    while True:
        item = await PLAYLIST_QUEUE.get()
        try:
            batch = await stage_index(item["job_id"], item["url"], item.get("limit"))
            job = JOBS.get(item["job_id"], {})
            if batch:
                await MATRIX_QUEUE.put(batch)
                await _emit(
                    item["job_id"],
                    "status",
                    stage="matrix_pending",
                    message="Stashed; waiting for matrix worker",
                    matrix_queue=MATRIX_QUEUE.qsize(),
                )
            elif job.get("status") == "error":
                await _finish_failed_playlist(item["job_id"], job.get("error") or "index failed")
        except Exception as exc:
            await _finish_failed_playlist(item["job_id"], str(exc))
        finally:
            PLAYLIST_QUEUE.task_done()


async def requeue_matrix(batch: Dict[str, Any], reason: str) -> None:
    job_id = batch["job_id"]
    job = JOBS.setdefault(job_id, {"job_id": job_id, "created_at": time.time()})
    attempts = int(job.get("attempts", 0)) + 1
    job.update(attempts=attempts, error=reason, updated_at=time.time())
    if attempts > MAX_ATTEMPTS:
        job.update(status="error", stage="gave_up", error=reason)
        await _emit(
            job_id,
            "gave_up",
            attempts=attempts,
            message=f"Matrix commit gave up after {MAX_ATTEMPTS} attempts: {reason}",
        )
        return
    delay = min(60, 2 ** attempts)
    job.update(status="retry_wait", stage="backoff")
    await _emit(
        job_id,
        "retry_scheduled",
        attempts=attempts,
        delay=delay,
        message=f"Matrix retry in {delay}s: {reason}",
    )
    await asyncio.sleep(delay)
    job.update(status="matrix_pending", stage="matrix")
    await MATRIX_QUEUE.put(batch)
    await _emit(job_id, "requeued", attempts=attempts, matrix_queue=MATRIX_QUEUE.qsize())


async def matrix_worker() -> None:
    """Consumes stashed indexes, computes matrices and commits them in order."""
    while True:
        batch = await MATRIX_QUEUE.get()
        try:
            await stage_matrix(batch)
            job = JOBS.get(batch["job_id"], {})
            if job.get("status") == "error":
                asyncio.create_task(
                    requeue_matrix(batch, job.get("error") or "matrix failed")
                )
        finally:
            MATRIX_QUEUE.task_done()


async def retry_failed_songs() -> Dict[str, int]:
    """Retry songs that had no lyrics, when providers/network are available again."""
    failed = await asyncio.to_thread(STORE.failed_all)
    now = time.time()
    candidates = [
        entry
        for entry in failed.values()
        if int(entry.get("attempts", 0)) < MAX_ATTEMPTS
        and now - float(entry.get("last_try", 0)) >= RETRY_INTERVAL
    ]
    if not candidates:
        return {"retried": 0, "resolved": 0}

    job_id = f"retry-{int(time.time() * 1000)}"
    JOBS[job_id] = {
        "job_id": job_id,
        "action": "retry_failed",
        "url": "failed-song-cache",
        "status": "indexing",
        "stage": "retry_failed",
        "created_at": time.time(),
    }
    await _emit(
        job_id,
        "status",
        stage="retry_failed",
        message=f"Retrying {len(candidates)} cached failed songs",
        total=len(candidates),
    )

    resolved: List[Dict[str, Any]] = []
    for position, entry in enumerate(candidates, start=1):
        text, backend = await asyncio.to_thread(
            fetch_lyrics,
            entry.get("title", ""),
            entry.get("artist", ""),
            entry.get("video_id", ""),
            None,
            entry.get("duration"),
        )
        if text:
            language = detect_language(text)
            song = {
                "video_id": entry["video_id"],
                "title": entry.get("title", ""),
                "artist": entry.get("artist", ""),
                "track": entry.get("title", ""),
                "language": language,
                "lyrics": text,
                "backend": backend,
            }
            if language not in ALLOWED_LANGUAGES:
                # Lyrics exist but the second filter rejects the language.
                await asyncio.to_thread(resolve_failed, entry["video_id"])
                await _emit(
                    job_id,
                    "language_skipped",
                    video_id=entry["video_id"],
                    title=song["track"],
                    artist=song["artist"],
                    language=language,
                    message=f"Skipped non-en/es song ({language})",
                )
                await asyncio.sleep(0.3)
                continue
            await asyncio.to_thread(save_cached_song, song)
            await asyncio.to_thread(resolve_failed, entry["video_id"])
            resolved.append(song)
            await _emit(
                job_id,
                "song_retry",
                index=position,
                total=len(candidates),
                video_id=entry["video_id"],
                title=song["track"],
                artist=song["artist"],
                language=song["language"],
                backend=backend,
                has_lyrics=True,
            )
        else:
            await asyncio.to_thread(
                STORE.failed_record, entry, "no lyrics", entry.get("duration")
            )
        await asyncio.sleep(0.3)

    if not resolved:
        JOBS[job_id].update(status="skipped", stage="retry_failed", reason="still no lyrics")
        await _emit(
            job_id,
            "skipped",
            reason=f"Retried {len(candidates)} songs; still no lyrics",
        )
        return {"retried": len(candidates), "resolved": 0}

    stash = await asyncio.to_thread(build_stash_index, resolved)
    path = await asyncio.to_thread(save_stash, job_id, resolved, stash)
    batch = {"job_id": job_id, "songs": resolved, "stash": stash, "path": path}
    JOBS[job_id].update(
        status="matrix_pending",
        stage="index_stash",
        stash_docs=stash["docs"],
        stash_terms=stash["terms"],
        stash_tokens=stash["tokens"],
        stash_path=path,
    )
    await _emit(
        job_id,
        "stashed",
        batch_id=job_id,
        docs=stash["docs"],
        terms=stash["terms"],
        tokens=stash["tokens"],
        path=path,
    )
    await MATRIX_QUEUE.put(batch)
    return {"retried": len(candidates), "resolved": len(resolved)}


async def retry_worker() -> None:
    await asyncio.sleep(min(15, RETRY_INTERVAL))
    while True:
        try:
            await retry_failed_songs()
        except Exception as exc:
            print("retry worker error:", exc)
        await asyncio.sleep(RETRY_INTERVAL)


async def queue_state_worker() -> None:
    while True:
        await asyncio.sleep(2)
        if QUEUE_DIRTY:
            await asyncio.to_thread(save_queue_state)


async def recover_queue() -> None:
    """Resume stashed batches and pending playlists after a cold start.

    All recovery state comes from MongoDB: the container filesystem is empty on
    every Cloud Run start.
    """
    stash_jobs = set()
    try:
        stashes = await asyncio.to_thread(STORE.stashes)
    except Exception as exc:  # pragma: no cover
        print(f"[lirify] stash recovery unavailable: {exc}", flush=True)
        stashes = []

    for batch in stashes:
        job_id = batch.get("job_id")
        if not job_id:
            continue
        stash_jobs.add(job_id)
        JOBS.setdefault(
            job_id,
            {
                "job_id": job_id,
                "action": "queue",
                "url": "recovered-stash",
                "status": "matrix_pending",
                "stage": "matrix",
                "created_at": time.time(),
            },
        ).update(status="matrix_pending", stage="matrix")
        await MATRIX_QUEUE.put(batch)

    try:
        pending = await asyncio.to_thread(STORE.jobs_pending)
    except Exception as exc:  # pragma: no cover
        print(f"[lirify] job recovery unavailable: {exc}", flush=True)
        pending = []

    for item in pending:
        job_id = item.get("job_id")
        if not job_id or job_id in JOBS or job_id in stash_jobs:
            continue
        if item.get("status") not in ("queued", "indexing", "retry_wait", "matrix_pending"):
            continue
        attempts = int(item.get("attempts", 0))
        if attempts > MAX_ATTEMPTS:
            continue
        JOBS[job_id] = {
            "job_id": job_id,
            "action": item.get("action", "queue"),
            "url": item.get("url"),
            "limit": item.get("limit"),
            "status": "queued",
            "stage": "recovered",
            "attempts": attempts,
            "source": item.get("source", "manual"),
            "created_at": item.get("created_at", time.time()),
        }
        if not item.get("url") or item.get("url") in ("recovered-stash",):
            JOBS[job_id].update(status="error", error="lost after cold start")
            await _emit(job_id, "error", message="Job lost its playlist URL across a cold start")
            continue
        await PLAYLIST_QUEUE.put(
            {
                "job_id": job_id,
                "url": item.get("url"),
                "limit": item.get("limit"),
                "attempts": attempts,
                "source": item.get("source", "manual"),
            }
        )
        await _emit(
            job_id,
            "recovered",
            message="Resumed from MongoDB job state",
            attempts=attempts,
        )
    await asyncio.to_thread(flush_jobs)


async def reconcile_vectors() -> None:
    """Populate Qdrant when it is empty but Atlas already has tracks."""
    if VECTORS.backend == "none":
        return
    try:
        count = await asyncio.to_thread(VECTORS.count)
    except Exception:
        count = 0
    songs = STATE["songs"]
    if not songs or count >= len(songs):
        return
    print(f"[lirify] backfilling {len(songs)} vectors into Qdrant", flush=True)
    await asyncio.to_thread(VECTORS.upsert, songs)


@app.on_event("startup")
async def start_workers() -> None:
    global GRPC_SERVER
    if os.environ.get("GRPC_INPROCESS", "1") != "0" and GRPC_SERVER is None:
        # One process = one index. The Caddy mux still fronts both protocols.
        # A failure here must not take REST down with it: report it and keep the
        # HTTP surface (and /health) alive.
        global GRPC_ERROR
        try:
            import grpc_server

            GRPC_SERVER = await grpc_server.start_server()
        except Exception as exc:  # pragma: no cover - port/bind problems
            GRPC_ERROR = f"{type(exc).__name__}: {exc}"
            print(f"[lirify] gRPC server failed to start: {GRPC_ERROR}", flush=True)
    if not WORKERS:
        await recover_queue()
        WORKERS.append(asyncio.create_task(reconcile_vectors()))
        WORKERS.append(asyncio.create_task(index_worker()))
        WORKERS.append(asyncio.create_task(matrix_worker()))
        WORKERS.append(asyncio.create_task(retry_worker()))
        WORKERS.append(asyncio.create_task(queue_state_worker()))


@app.on_event("shutdown")
async def stop_workers() -> None:
    global GRPC_SERVER
    for task in WORKERS:
        task.cancel()
    WORKERS.clear()
    if GRPC_SERVER is not None:
        import grpc_server

        await grpc_server.stop_server(GRPC_SERVER)
        GRPC_SERVER = None


@app.websocket("/ws")
async def ws_progress(ws: WebSocket):
    await hub.connect(ws)
    await ws.send_json(
        {
            "event": "connected",
            "message": "Lirify live progress stream",
            "indexed_songs": len(STATE["songs"]),
            "ts": time.time(),
        }
    )
    try:
        while True:
            raw = await ws.receive_text()
            try:
                cmd = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"event": "error", "message": "Invalid JSON"})
                continue
            action = cmd.get("action", "status")
            if action == "ping":
                await ws.send_json({"event": "pong", "ts": time.time()})
                continue
            if action == "status":
                await ws.send_json(
                    {
                        "event": "status",
                        "indexed_songs": len(STATE["songs"]),
                        "build": STATE.get("build", {}),
                        "jobs": JOBS,
                        "playlist_queue": PLAYLIST_QUEUE.qsize(),
                        "matrix_queue": MATRIX_QUEUE.qsize(),
                        "ts": time.time(),
                    }
                )
                continue
            url = cmd.get("url", "")
            limit = cmd.get("limit")
            job_id = cmd.get("job_id") or f"job-{int(time.time() * 1000)}"
            if action == "extract":
                if not url:
                    await ws.send_json({"event": "error", "job_id": job_id, "message": "url is required"})
                    continue
                asyncio.create_task(run_extract_job(job_id, url, limit))
            elif action == "index":
                if not url:
                    await ws.send_json({"event": "error", "job_id": job_id, "message": "url is required"})
                    continue
                asyncio.create_task(run_index_job(job_id, url, limit))
            elif action == "queue":
                urls = list(
                    dict.fromkeys(
                        u.strip()
                        for u in ([url] if url else []) + list(cmd.get("urls") or [])
                        if u.strip()
                    )
                )
                if not urls:
                    await ws.send_json(
                        {"event": "error", "job_id": job_id, "message": "url or urls is required"}
                    )
                    continue
                jobs = [await enqueue_playlist(u, limit) for u in urls]
                await ws.send_json(
                    {
                        "event": "queued_batch",
                        "jobs": jobs,
                        "count": len(jobs),
                        "queue_size": PLAYLIST_QUEUE.qsize(),
                        "ts": time.time(),
                    }
                )
            else:
                await ws.send_json(
                    {"event": "error", "job_id": job_id, "message": f"Unknown action: {action}"}
                )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(ws)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "indexed_songs": len(STATE["songs"]),
        "storage": {"tracks": STORE.backend, "vectors": VECTORS.backend},
        # Surfaced so operators (and CI annotations) can see a broken gRPC
        # listener without reading container logs.
        "grpc": "up" if GRPC_SERVER is not None else "down",
        "grpc_error": GRPC_ERROR,
    }


@app.get("/providers")
def providers():
    return {
        "count": len(LYRICS_PROVIDERS),
        "providers": [name for name, _ in LYRICS_PROVIDERS],
        "order": "Limusic default order",
    }


@app.post("/extract")
def extract(inp: UrlIn):
    ids = extract_video_ids(inp.url)
    if inp.limit:
        ids = ids[: inp.limit]
    return {
        "count": len(ids),
        "ids": ids,
        "url": inp.url,
        "extracted": True,
        "persisted": False,
    }


@app.post("/index")
async def index(inp: UrlIn):
    """Synchronous single-playlist indexing (also accumulates into the live index)."""
    job_id = f"sync-{int(time.time() * 1000)}"
    await run_index_job(job_id, inp.url, inp.limit)
    job = JOBS.get(job_id, {})
    if job.get("status") == "error":
        raise HTTPException(400, job.get("error", "Indexing failed"))
    return {
        "status": job.get("status", "committed"),
        "added": job.get("added", 0),
        "stats": STATE.get("build", {}),
    }


@app.post("/queue")
async def queue_playlists(inp: QueueIn):
    urls = list(
        dict.fromkeys(
            u.strip()
            for u in ([inp.url] if inp.url else []) + list(inp.urls or [])
            if u.strip()
        )
    )
    if not urls:
        raise HTTPException(400, "At least one url is required")
    jobs = [
        await enqueue_playlist(url.strip(), inp.limit, (inp.source or "manual"))
        for url in urls
    ]
    return {
        "queued": len(jobs),
        "jobs": jobs,
        "queue_size": PLAYLIST_QUEUE.qsize(),
    }


@app.post("/retry")
async def retry_failed():
    """Run one failed-song retry pass immediately."""
    return await retry_failed_songs()


@app.get("/cache")
def cache_status():
    failed = STORE.failed_all()
    return {
        "cached_lyrics": STORE.cached_lyric_count(),
        "failed_songs": len(failed),
        "max_attempts": MAX_ATTEMPTS,
        "retry_interval_seconds": RETRY_INTERVAL,
        "storage": STORE.backend,
        "failed": list(failed.values())[:100],
    }


@app.get("/queue")
def queue_status():
    jobs = sorted(JOBS.values(), key=lambda j: j.get("created_at", 0), reverse=True)
    stashed = len(STORE.stashes())
    return {
        "playlist_queue": PLAYLIST_QUEUE.qsize(),
        "matrix_queue": MATRIX_QUEUE.qsize(),
        "stashed_batches": stashed,
        "cached_lyrics": STORE.cached_lyric_count(),
        "failed_songs": STORE.failed_count(),
        "storage": STORE.backend,
        "jobs": jobs[:100],
    }


@app.get("/stats")
def stats():
    build = dict(STATE.get("build") or {})
    matrices = STATE.get("matrices") or {}
    return {
        "indexed_songs": len(STATE["songs"]),
        "video_ids": len(STATE.get("ids") or []),
        "vocabulary_size": build.get("vocabulary_size", 0),
        "inverted_terms": build.get("inverted_terms", 0),
        "lyrics_tokens": build.get("lyrics_tokens", 0),
        "languages": build.get("languages", {}),
        "backends": build.get("backends", {}),
        "weights": WEIGHTS,
        "lyrics_providers": [name for name, _ in LYRICS_PROVIDERS],
        "allowed_languages": sorted(ALLOWED_LANGUAGES),
        "queue": {
            "playlist_pending": PLAYLIST_QUEUE.qsize(),
            "matrix_pending": MATRIX_QUEUE.qsize(),
            "jobs": len(JOBS),
            "cached_lyrics": STORE.cached_lyric_count(),
            "failed_songs": STORE.failed_count(),
            "max_attempts": MAX_ATTEMPTS,
            "retry_interval_seconds": RETRY_INTERVAL,
        },
        "matrix_shape": [
            len(STATE["songs"]),
            len(STATE["songs"]),
        ],
        "matrices_available": sorted(matrices.keys()),
        "storage": {
            "tracks": STORE.backend,
            "vectors": VECTORS.backend,
            "stateless": True,
            "max_indexed_songs": MAX_INDEXED_SONGS,
            "catalog_songs": STORE.count_songs(),
        },
        "limits": {
            "public_read_per_minute": PUBLIC_RATE_LIMIT,
            "bot_per_window": int(os.environ.get("BOT_RATE_LIMIT", "30")),
            "bot_window_seconds": int(os.environ.get("BOT_RATE_WINDOW_SECONDS", "3600")),
        },
        "top_terms": sorted(
            STATE.get("vocab", []),
            key=lambda t: -len(STATE.get("index", {}).get(t, {})),
        )[:25],
    }


@app.get("/matrices")
def matrices():
    if not STATE["songs"]:
        raise HTTPException(404, "Nothing indexed yet")
    out = {}
    for key, matrix in STATE["matrices"].items():
        out[key] = {
            "shape": list(matrix.shape),
            "values": np.round(matrix, 6).tolist(),
        }
    out["_meta"] = {
        "songs": [
            {"video_id": s["video_id"], "title": s["track"], "artist": s["artist"]}
            for s in STATE["songs"]
        ],
        "weights": WEIGHTS,
    }
    return out


def _search_scores(query: str) -> np.ndarray:
    vocab = STATE.get("vocab") or []
    index = STATE.get("index") or {}
    doc_freq = STATE.get("doc_freq")
    if not vocab or doc_freq is None:
        # Partially built state: return a correctly sized zero vector instead of
        # an empty one, so callers can index by song position safely.
        return np.zeros(len(STATE.get("songs") or []), dtype=np.float32)
    q_tokens = normalize_lyrics(query, "en")
    q_counts = np.zeros(len(vocab), dtype=np.float32)
    pos = {term: i for i, term in enumerate(vocab)}
    for token in q_tokens:
        if token in pos:
            q_counts[pos[token]] += 1
    if not q_counts.any():
        return np.zeros(len(STATE.get("songs") or []), dtype=np.float32)
    tf = np.zeros_like(q_counts)
    mask = q_counts > 0
    tf[mask] = np.log10(q_counts[mask]) + 1.0
    docs = max(len(STATE.get("songs") or []), 1)
    df = doc_freq
    idf = np.log10(docs / np.where(df == 0, 1, df))
    q = tf * idf
    norm = np.linalg.norm(q)
    if norm:
        q = q / norm
    return q @ STATE["tfidf"]


@app.get("/search")
def search(q: str, limit: int = 20):
    if not STATE["songs"]:
        return {"query": q, "results": []}
    scores = _search_scores(q)
    q_tokens = set(normalize_name(q).split())
    if q_tokens:
        for i, s in enumerate(STATE["songs"]):
            name_tokens = set(normalize_name(s["track"]).split())
            artist_tokens = set(normalize_artist(s["artist"]).split())
            name_hit = len(q_tokens & name_tokens) / max(len(q_tokens), 1)
            artist_hit = len(q_tokens & artist_tokens) / max(len(q_tokens), 1)
            scores[i] += 0.5 * name_hit + 0.3 * artist_hit
    ranked = np.argsort(-scores)[:limit]
    results = []
    for i in ranked:
        if scores[i] <= 0:
            continue
        s = STATE["songs"][int(i)]
        results.append(
            {
                "video_id": s["video_id"],
                "title": s["track"],
                "artist": s["artist"],
                "language": s["language"],
                "score": round(float(scores[i]), 6),
            }
        )
    return {"query": q, "results": results}


def _summary(song: Dict[str, Any], score: float) -> Dict[str, Any]:
    return {
        "video_id": song["video_id"],
        "title": song["track"],
        "artist": song["artist"],
        "language": song["language"],
        "score": round(float(score), 6),
    }


def _meta_similarity(seed: Dict[str, Any], candidate: Dict[str, Any]) -> float:
    """Name/artist/language share of the unified score (lyrics come from vectors)."""

    def jaccard(a: str, b: str) -> float:
        sa, sb = set(a.split()), set(b.split())
        if not sa and not sb:
            return 1.0
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    score = WEIGHTS["name"] * jaccard(
        normalize_name(seed.get("track", "")), normalize_name(candidate.get("track", ""))
    )
    score += WEIGHTS["artist"] * jaccard(
        normalize_artist(seed.get("artist", "")),
        normalize_artist(candidate.get("artist", "")),
    )
    seed_lang = normalize_lang(seed.get("language", ""))
    if seed_lang and seed_lang == normalize_lang(candidate.get("language", "")):
        score += WEIGHTS["lang"]
    return score


def recommend_songs(seed_video_ids: List[str], limit: int = 10) -> Dict[str, Any]:
    """Rank tracks similar to the seeds.

    Seeds arrive from the caller (the browser owns the listening history). Qdrant
    answers the lyric-similarity question; the small name/artist/language terms
    are blended in from the committed index. Without Qdrant the in-process
    unified matrix is used, so local development keeps working.
    """
    ids = STATE.get("ids") or []
    songs = STATE.get("songs") or []
    seeds = [v for v in dict.fromkeys(seed_video_ids) if v in ids]
    if not seeds:
        return {"seed_video_id": "", "recommendations": [], "engine": "none"}

    by_id = {s["video_id"]: s for s in songs}
    seed_song = by_id.get(seeds[0])
    if seed_song is None:
        return {"seed_video_id": "", "recommendations": [], "engine": "none"}
    limit = max(1, min(int(limit or 10), 50))

    if VECTORS.backend != "none":
        totals: Dict[str, float] = {}
        for position, seed in enumerate(seeds[:5]):
            weight = 1.0 / (1 + position)
            for candidate_id, similarity in VECTORS.neighbours(seed, limit * 3):
                if candidate_id in seeds or candidate_id not in by_id:
                    continue
                totals[candidate_id] = totals.get(candidate_id, 0.0) + weight * float(similarity)
        ranked = sorted(totals.items(), key=lambda item: -item[1])[:limit]
        results = []
        for candidate_id, similarity in ranked:
            candidate = by_id[candidate_id]
            score = WEIGHTS["lyrics"] * similarity + _meta_similarity(seed_song, candidate)
            results.append(_summary(candidate, score))
        if results:
            return {
                "seed_video_id": seeds[0],
                "seed_video_ids": seeds,
                "recommendations": results,
                "engine": "qdrant",
            }

    matrix = (STATE.get("matrices") or {}).get("unified")
    if matrix is None:
        return {"seed_video_id": seeds[0], "recommendations": [], "engine": "none"}
    row = ids.index(seeds[0])
    scores = matrix[row]
    order = np.argsort(-scores)
    out = []
    for index in order:
        if int(index) == row:
            continue
        out.append(_summary(songs[int(index)], scores[int(index)]))
        if len(out) >= limit:
            break
    return {
        "seed_video_id": seeds[0],
        "seed_video_ids": seeds,
        "recommendations": out,
        "engine": "matrix",
    }


@app.get("/recommend/{video_id}")
def recommend(video_id: str, limit: int = 10, seeds: str = ""):
    seed_list = [video_id] + [s.strip() for s in seeds.split(",") if s.strip()]
    payload = recommend_songs(seed_list, limit)
    if not payload["recommendations"] and video_id not in (STATE.get("ids") or []):
        raise HTTPException(404, "Unknown video id")
    return {"video_id": video_id, **payload}


@app.get("/song/{video_id}")
def song(video_id: str):
    for s in STATE["songs"]:
        if s["video_id"] == video_id:
            return s
    raise HTTPException(404, "Unknown video id")


@app.get("/songs")
def songs(offset: int = 0, limit: int = 50):
    return {
        "total": len(STATE["songs"]),
        "songs": STATE["songs"][offset : offset + limit],
    }


# ---------------------------------------------------------------------------
# Bot ingestion API (HTTP/JSON, bearer protected)
# ---------------------------------------------------------------------------


def job_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
    """Job state for machine clients: memory first, then MongoDB."""
    job = JOBS.get(job_id)
    if job:
        return dict(job)
    try:
        return STORE.job_get(job_id)
    except Exception:
        return None


app.include_router(
    build_bot_router(
        enqueue=enqueue_playlist,
        get_job=job_snapshot,
        store=STORE,
        rate_limit=int(os.environ.get("BOT_RATE_LIMIT", "30")),
        rate_window=int(os.environ.get("BOT_RATE_WINDOW_SECONDS", "3600")),
    )
)


# ---------------------------------------------------------------------------
# Player UI API (additive; serves the Astro client)
# ---------------------------------------------------------------------------
# The routes live in player_api.py and only read the state built above. They never
# change indexing, ranking, search or recommendation behaviour.
from player_api import build_router as _build_player_router

app.include_router(_build_player_router(lambda: STATE, search, recommend))
