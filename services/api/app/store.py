"""Persistence for python-backend.

Cloud Run containers are disposable: every byte that must survive a cold start
lives in MongoDB Atlas. This module is the only place that talks to Mongo and it
never opens a local file.

Design notes
------------
* Documents use camelCase fields, a ``schemaVersion`` and ``createdAt`` /
  ``updatedAt`` timestamps, i.e. the shape Mongoose produces by default. The
  ``$jsonSchema`` validators installed by :func:`ensure_schema` match the
  Mongoose models in ``docs/MONGODB_SCHEMA.md``.
* Collections (plural, lowercase): ``songs``, ``lyrics_cache``, ``failed_songs``,
  ``jobs``, ``stashes``, ``index_stats``, ``media_durations``,
  ``bot_rate_limits``, ``bot_idempotency``.
* ``MemoryStore`` implements the same interface and is selected when
  ``MONGODB_URI`` is unset. It is a local-development convenience only: it is
  still stateless across restarts, but shared state requires Atlas.
* Every method is synchronous; callers run them through ``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 1

COLLECTIONS = {
    "songs": "songs",
    "cache": "lyrics_cache",
    "failed": "failed_songs",
    "jobs": "jobs",
    "stashes": "stashes",
    "stats": "index_stats",
    "durations": "media_durations",
    "rate": "bot_rate_limits",
    "idempotency": "bot_idempotency",
}

# ---------------------------------------------------------------------------
# Validation / indexes. Mirrors docs/MONGODB_SCHEMA.md (Mongoose definitions).
# ---------------------------------------------------------------------------

_VALIDATORS: Dict[str, Dict[str, Any]] = {
    COLLECTIONS["songs"]: {
        "bsonType": "object",
        "required": ["videoId", "title", "artist", "language", "lyrics"],
        "properties": {
            "videoId": {"bsonType": "string", "pattern": "^[A-Za-z0-9_-]{11}$"},
            "title": {"bsonType": "string"},
            "youtubeTitle": {"bsonType": "string"},
            "artist": {"bsonType": "string"},
            "language": {"bsonType": "string"},
            "lyrics": {"bsonType": "string"},
            "backend": {"bsonType": "string"},
            "duration": {"bsonType": ["double", "int", "null"]},
            "schemaVersion": {"bsonType": "int"},
            "createdAt": {"bsonType": "date"},
            "updatedAt": {"bsonType": "date"},
        },
    },
    COLLECTIONS["cache"]: {
        "bsonType": "object",
        "required": ["videoId", "lyrics"],
        "properties": {
            "videoId": {"bsonType": "string"},
            "lyrics": {"bsonType": "string"},
            "cachedAt": {"bsonType": "date"},
        },
    },
    COLLECTIONS["failed"]: {
        "bsonType": "object",
        "required": ["videoId", "attempts"],
        "properties": {
            "videoId": {"bsonType": "string"},
            "attempts": {"bsonType": "int"},
            "lastTry": {"bsonType": "date"},
        },
    },
    COLLECTIONS["jobs"]: {
        "bsonType": "object",
        "required": ["jobId", "status"],
        "properties": {
            "jobId": {"bsonType": "string"},
            "status": {"bsonType": "string"},
            "createdAt": {"bsonType": "date"},
            "updatedAt": {"bsonType": "date"},
        },
    },
}

_INDEXES: Dict[str, List[Tuple[str, bool]]] = {
    COLLECTIONS["songs"]: [("videoId", True), ("language", False)],
    COLLECTIONS["cache"]: [("videoId", True)],
    COLLECTIONS["failed"]: [("videoId", True), ("lastTry", False)],
    COLLECTIONS["jobs"]: [("jobId", True), ("status", False), ("createdAt", False)],
    COLLECTIONS["stashes"]: [("jobId", True)],
    COLLECTIONS["durations"]: [("videoId", True)],
    COLLECTIONS["idempotency"]: [("createdAt", False)],
}


def _now() -> float:
    return time.time()


def redact_uri(uri: str) -> str:
    """Connection string safe for logs: host, database and user, never the password."""
    match = re.match(
        r"^(mongodb(?:\+srv)?)://(?:([^:@/]+)(?::[^@/]*)?@)?([^/?]+)(?:/([^?]*))?",
        (uri or "").strip(),
    )
    if not match:
        return "<invalid uri>"
    scheme, user, host, database = match.groups()
    return f"{scheme}://{user + '@' if user else ''}{host}/{database or ''}"


def _iso(value: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", value or "unknown")[:180]


class Store:
    """Interface shared by MongoStore and MemoryStore."""

    backend = "abstract"

    # --- songs / index ----------------------------------------------------
    def load_songs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return committed songs, optionally capped to the newest ``limit`` rows."""
        raise NotImplementedError

    def count_songs(self) -> int:
        raise NotImplementedError

    def commit_songs(self, songs: List[Dict[str, Any]], build: Dict[str, Any]) -> int:
        raise NotImplementedError

    def cached_lyric_count(self) -> int:
        raise NotImplementedError

    def prune_songs(self, keep_ids: Iterable[str]) -> int:
        raise NotImplementedError

    # --- lyric cache ------------------------------------------------------
    def cache_get(self, video_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def cache_put(self, song: Dict[str, Any]) -> None:
        raise NotImplementedError

    # --- failed songs -----------------------------------------------------
    def failed_all(self) -> Dict[str, Dict[str, Any]]:
        raise NotImplementedError

    def failed_record(self, song: Dict[str, Any], reason: str, duration: Optional[float]) -> None:
        raise NotImplementedError

    def failed_resolve(self, video_id: str) -> None:
        raise NotImplementedError

    def failed_count(self) -> int:
        raise NotImplementedError

    # --- jobs -------------------------------------------------------------
    def job_put(self, job: Dict[str, Any]) -> None:
        raise NotImplementedError

    def job_get(self, job_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def jobs_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def jobs_pending(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    # --- stashes ----------------------------------------------------------
    def stash_put(self, job_id: str, songs: List[Dict[str, Any]], stash: Dict[str, Any]) -> None:
        raise NotImplementedError

    def stashes(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def stash_delete(self, job_id: str) -> None:
        raise NotImplementedError

    # --- stats ------------------------------------------------------------
    def stats_get(self) -> Dict[str, Any]:
        raise NotImplementedError

    def stats_revision(self) -> int:
        """Monotonic counter bumped on every committed batch.

        Instances compare it with the revision they loaded to decide whether their
        in-memory index is stale (local indexing writes to the shared Atlas/Qdrant
        state, so the cloud instance must notice).
        """
        raise NotImplementedError

    def stats_put(self, build: Dict[str, Any]) -> None:
        raise NotImplementedError

    # --- media durations (replaces data/ui_media.json) ---------------------
    def durations_all(self) -> Dict[str, float]:
        raise NotImplementedError

    def duration_put(self, video_id: str, duration: float) -> None:
        raise NotImplementedError

    # --- bot support ------------------------------------------------------
    def rate_limit_hit(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int, int]:
        raise NotImplementedError

    def idempotent_job(self, key: str) -> Optional[str]:
        raise NotImplementedError

    def remember_idempotent_job(self, key: str, job_id: str, ttl_days: int = 7) -> None:
        raise NotImplementedError

    def ping(self) -> bool:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# MongoDB Atlas
# ---------------------------------------------------------------------------


class MongoStore(Store):
    backend = "mongodb"
    init_error = ""

    def __init__(self, uri: str, db_name: str = "lirify") -> None:
        from pymongo import ASCENDING, DESCENDING, MongoClient
        from pymongo.errors import CollectionInvalid

        if not re.match(r"^mongodb(\+srv)?://", uri.strip()):
            raise ValueError(
                "MONGODB_URI must start with mongodb:// or mongodb+srv:// "
                f"(got {redact_uri(uri)!r})"
            )
        print(
            f"[lirify] mongo target {redact_uri(uri)} db={db_name}", flush=True
        )

        self._asc = ASCENDING
        self._desc = DESCENDING
        self.client = MongoClient(
            uri,
            serverSelectionTimeoutMS=int(os.environ.get("MONGODB_TIMEOUT_MS", "8000")),
            maxPoolSize=int(os.environ.get("MONGODB_POOL_SIZE", "10")),
            retryWrites=True,
            appname="lirify-python-backend",
        )
        self.db = self.client[db_name]
        self._collection_invalid = CollectionInvalid
        # A wrong URI/password or an Atlas IP allowlist must degrade this process,
        # not kill it: an exception here would abort module import and leave Cloud
        # Run with a container that answers 502 forever.
        try:
            self.ensure_schema()
        except Exception as exc:  # pragma: no cover - bad credentials / network
            self.init_error = f"{type(exc).__name__}: {exc}"
            print(f"[lirify] MongoDB init failed: {self.init_error}", flush=True)

    # -- schema -----------------------------------------------------------
    def ensure_schema(self) -> None:
        from pymongo.errors import CollectionInvalid, OperationFailure

        existing = set(self.db.list_collection_names())
        for name, validator in _VALIDATORS.items():
            if name not in existing:
                try:
                    self.db.create_collection(
                        name,
                        validator={"$jsonSchema": validator},
                        validationLevel="moderate",
                        validationAction="warn",
                    )
                except CollectionInvalid:
                    pass
        for name, indexes in _INDEXES.items():
            for field, unique in indexes:
                try:
                    self.db[name].create_index(
                        [(field, self._asc)], unique=unique, background=True
                    )
                except OperationFailure:
                    pass
        # TTL indexes keep the bot-facing collections from growing forever.
        try:
            self.db[COLLECTIONS["rate"]].create_index("resetAt", expireAfterSeconds=3600)
            self.db[COLLECTIONS["idempotency"]].create_index(
                "createdAt", expireAfterSeconds=7 * 24 * 3600
            )
        except OperationFailure:
            pass

    def ping(self) -> bool:
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False

    # -- songs ------------------------------------------------------------
    def load_songs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        # Without a cap, oldest-first keeps document ids stable. With a cap, take
        # the newest N (recent playlist additions stay visible) and restore the
        # ascending order afterwards.
        if limit is not None and limit > 0:
            cursor = (
                self.db[COLLECTIONS["songs"]]
                .find({})
                .sort("createdAt", self._desc)
                .limit(limit)
            )
            docs = list(cursor)
            docs.reverse()
        else:
            docs = list(self.db[COLLECTIONS["songs"]].find({}).sort("createdAt", 1))
        for doc in docs:
            out.append(
                {
                    "video_id": doc.get("videoId", ""),
                    "track": doc.get("title", ""),
                    "title": doc.get("youtubeTitle", "") or doc.get("title", ""),
                    "artist": doc.get("artist", ""),
                    "language": doc.get("language", ""),
                    "lyrics": doc.get("lyrics", ""),
                    "backend": doc.get("backend", ""),
                    "duration": doc.get("duration"),
                }
            )
        return out

    def count_songs(self) -> int:
        return int(self.db[COLLECTIONS["songs"]].count_documents({}))

    def stats_revision(self) -> int:
        doc = self.db[COLLECTIONS["stats"]].find_one({"_id": "global"}, {"revision": 1})
        return int((doc or {}).get("revision", 0))

    def commit_songs(self, songs: List[Dict[str, Any]], build: Dict[str, Any]) -> int:
        from pymongo import UpdateOne

        if not songs:
            return 0
        now = _now()
        ops = []
        for song in songs:
            video_id = song.get("video_id") or ""
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            ops.append(
                UpdateOne(
                    {"videoId": video_id},
                    {
                        "$set": {
                            "title": song.get("track") or song.get("title", ""),
                            "youtubeTitle": song.get("title", ""),
                            "artist": song.get("artist", ""),
                            "language": song.get("language", ""),
                            "lyrics": song.get("lyrics", ""),
                            "backend": song.get("backend") or "",
                            "duration": song.get("duration"),
                            "schemaVersion": SCHEMA_VERSION,
                            "updatedAt": now,
                        },
                        "$setOnInsert": {"createdAt": now},
                    },
                    upsert=True,
                )
            )
        if not ops:
            return 0
        result = self.db[COLLECTIONS["songs"]].bulk_write(ops, ordered=False)
        self.stats_put(build)
        # Bumping the revision is what tells other replicas their cached index is
        # stale; it is incremented once per committed batch, not per song.
        self.db[COLLECTIONS["stats"]].update_one(
            {"_id": "global"}, {"$inc": {"revision": 1}}, upsert=True
        )
        return int(result.upserted_count + result.modified_count)

    def prune_songs(self, keep_ids: Iterable[str]) -> int:
        keep = [v for v in keep_ids if v]
        if not keep:
            return 0
        result = self.db[COLLECTIONS["songs"]].delete_many({"videoId": {"$nin": keep}})
        return int(result.deleted_count)

    def cached_lyric_count(self) -> int:
        return int(self.db[COLLECTIONS["cache"]].count_documents({}))

    # -- lyric cache ------------------------------------------------------
    def cache_get(self, video_id: str) -> Optional[Dict[str, Any]]:
        doc = self.db[COLLECTIONS["cache"]].find_one({"videoId": video_id})
        if not doc:
            return None
        if not (doc.get("lyrics") or "").strip():
            return None
        return {
            "video_id": doc.get("videoId", ""),
            "title": doc.get("youtubeTitle", "") or doc.get("title", ""),
            "artist": doc.get("artist", ""),
            "track": doc.get("title", ""),
            "language": doc.get("language", ""),
            "lyrics": doc.get("lyrics", ""),
            "backend": doc.get("backend", ""),
            "cached_at": doc.get("cachedAt"),
        }

    def cache_put(self, song: Dict[str, Any]) -> None:
        lyrics = (song.get("lyrics") or "").strip()
        if not lyrics:
            return
        video_id = song.get("video_id", "")
        if not video_id:
            return
        self.db[COLLECTIONS["cache"]].update_one(
            {"videoId": video_id},
            {
                "$set": {
                    "videoId": video_id,
                    "title": song.get("track") or song.get("title", ""),
                    "youtubeTitle": song.get("title", ""),
                    "artist": song.get("artist", ""),
                    "language": song.get("language", ""),
                    "lyrics": song.get("lyrics", ""),
                    "backend": song.get("backend", ""),
                    "cachedAt": _now(),
                    "schemaVersion": SCHEMA_VERSION,
                }
            },
            upsert=True,
        )

    # -- failed -----------------------------------------------------------
    def failed_all(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for doc in self.db[COLLECTIONS["failed"]].find({}):
            video_id = doc.get("videoId", "")
            out[video_id] = {
                "video_id": video_id,
                "title": doc.get("title", ""),
                "artist": doc.get("artist", ""),
                "duration": doc.get("duration"),
                "attempts": int(doc.get("attempts", 0)),
                "reason": doc.get("reason", ""),
                "last_try": doc.get("lastTry", 0),
            }
        return out

    def failed_record(self, song: Dict[str, Any], reason: str, duration: Optional[float]) -> None:
        video_id = song.get("video_id", "")
        if not video_id:
            return
        self.db[COLLECTIONS["failed"]].update_one(
            {"videoId": video_id},
            {
                "$inc": {"attempts": 1},
                "$set": {
                    "videoId": video_id,
                    "title": song.get("track") or song.get("title", ""),
                    "artist": song.get("artist", ""),
                    "duration": duration,
                    "reason": reason,
                    "lastTry": _now(),
                    "schemaVersion": SCHEMA_VERSION,
                },
            },
            upsert=True,
        )

    def failed_resolve(self, video_id: str) -> None:
        self.db[COLLECTIONS["failed"]].delete_one({"videoId": video_id})

    def failed_count(self) -> int:
        return int(self.db[COLLECTIONS["failed"]].count_documents({}))

    # -- jobs -------------------------------------------------------------
    def job_put(self, job: Dict[str, Any]) -> None:
        job_id = job.get("job_id")
        if not job_id:
            return
        now = _now()
        doc = {
            "jobId": job_id,
            "action": job.get("action", "queue"),
            "url": job.get("url", ""),
            "limit": job.get("limit"),
            "status": job.get("status", "queued"),
            "stage": job.get("stage", ""),
            "attempts": int(job.get("attempts", 0)),
            "error": job.get("error"),
            "errorCode": job.get("error_code"),
            "added": int(job.get("added", 0)),
            "source": job.get("source", "manual"),
            "batchId": job.get("batch_id"),
            "lastEvent": job.get("last_event"),
            "updatedAt": now,
            "schemaVersion": SCHEMA_VERSION,
        }
        self.db[COLLECTIONS["jobs"]].update_one(
            {"jobId": job_id},
            {"$set": doc, "$setOnInsert": {"createdAt": job.get("created_at", now)}},
            upsert=True,
        )

    @staticmethod
    def _job_out(doc: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": doc.get("jobId"),
            "action": doc.get("action"),
            "url": doc.get("url"),
            "limit": doc.get("limit"),
            "status": doc.get("status"),
            "stage": doc.get("stage"),
            "attempts": int(doc.get("attempts", 0)),
            "error": doc.get("error"),
            "error_code": doc.get("errorCode"),
            "added": int(doc.get("added", 0)),
            "source": doc.get("source"),
            "batch_id": doc.get("batchId"),
            "last_event": doc.get("lastEvent"),
            "created_at": doc.get("createdAt", 0),
            "updated_at": doc.get("updatedAt", 0),
        }

    def job_get(self, job_id: str) -> Optional[Dict[str, Any]]:
        doc = self.db[COLLECTIONS["jobs"]].find_one({"jobId": job_id})
        return self._job_out(doc) if doc else None

    def jobs_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = (
            self.db[COLLECTIONS["jobs"]]
            .find({})
            .sort("createdAt", self._desc)
            .limit(max(1, min(limit, 500)))
        )
        return [self._job_out(doc) for doc in cursor]

    def jobs_pending(self) -> List[Dict[str, Any]]:
        cursor = self.db[COLLECTIONS["jobs"]].find(
            {"status": {"$nin": ["committed", "skipped"]}}
        )
        return [self._job_out(doc) for doc in cursor]

    # -- stashes ----------------------------------------------------------
    def stash_put(self, job_id: str, songs: List[Dict[str, Any]], stash: Dict[str, Any]) -> None:
        self.db[COLLECTIONS["stashes"]].replace_one(
            {"jobId": job_id},
            {
                "jobId": job_id,
                "songs": songs,
                "stash": stash,
                "createdAt": _now(),
                "schemaVersion": SCHEMA_VERSION,
            },
            upsert=True,
        )

    def stashes(self) -> List[Dict[str, Any]]:
        out = []
        for doc in self.db[COLLECTIONS["stashes"]].find({}):
            if not doc.get("songs") or not doc.get("stash"):
                continue
            out.append(
                {
                    "job_id": doc.get("jobId"),
                    "songs": doc.get("songs"),
                    "stash": doc.get("stash"),
                }
            )
        return out

    def stash_delete(self, job_id: str) -> None:
        self.db[COLLECTIONS["stashes"]].delete_one({"jobId": job_id})

    # -- stats ------------------------------------------------------------
    def stats_get(self) -> Dict[str, Any]:
        doc = self.db[COLLECTIONS["stats"]].find_one({"_id": "global"})
        if not doc:
            return {}
        return doc.get("build") or {}

    def stats_put(self, build: Dict[str, Any]) -> None:
        # update_one, not replace_one: replacing the document would drop the
        # `revision` counter, so replicas could never detect a newer index.
        self.db[COLLECTIONS["stats"]].update_one(
            {"_id": "global"},
            {
                "$set": {
                    "build": build,
                    "updatedAt": _now(),
                    "schemaVersion": SCHEMA_VERSION,
                },
                "$setOnInsert": {"revision": 0},
            },
            upsert=True,
        )

    # -- durations --------------------------------------------------------
    def durations_all(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for doc in self.db[COLLECTIONS["durations"]].find({}):
            try:
                out[doc.get("videoId", "")] = float(doc.get("duration") or 0)
            except (TypeError, ValueError):
                continue
        return out

    def duration_put(self, video_id: str, duration: float) -> None:
        if not video_id or not duration:
            return
        self.db[COLLECTIONS["durations"]].update_one(
            {"videoId": video_id},
            {"$set": {"videoId": video_id, "duration": float(duration), "updatedAt": _now()}},
            upsert=True,
        )

    # -- bot --------------------------------------------------------------
    def rate_limit_hit(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int, int]:
        from pymongo import ReturnDocument
        from pymongo.errors import DuplicateKeyError

        now = _now()
        reset_at = now + max(1, window_seconds)
        coll = self.db[COLLECTIONS["rate"]]
        doc = coll.find_one_and_update(
            {"_id": key, "resetAt": {"$gt": now}},
            {"$inc": {"count": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            try:
                coll.insert_one({"_id": key, "count": 1, "resetAt": reset_at})
                return True, 1, int(reset_at - now)
            except DuplicateKeyError:
                doc = coll.find_one_and_update(
                    {"_id": key},
                    {"$set": {"resetAt": reset_at}, "$setOnInsert": {"count": 0}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
        count = int((doc or {}).get("count", 1))
        remaining = max(0, int((doc or {}).get("resetAt", reset_at) - now))
        return count <= limit, count, remaining

    def idempotent_job(self, key: str) -> Optional[str]:
        if not key:
            return None
        doc = self.db[COLLECTIONS["idempotency"]].find_one({"_id": key})
        return doc.get("jobId") if doc else None

    def remember_idempotent_job(self, key: str, job_id: str, ttl_days: int = 7) -> None:
        if not key:
            return
        try:
            self.db[COLLECTIONS["idempotency"]].update_one(
                {"_id": key},
                {"$set": {"jobId": job_id, "createdAt": _now()}},
                upsert=True,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# In-memory fallback for `docker compose up` without Atlas
# ---------------------------------------------------------------------------


class MemoryStore(Store):
    backend = "memory"
    init_error = ""

    def __init__(self) -> None:
        self._songs: Dict[str, Dict[str, Any]] = {}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._failed: Dict[str, Dict[str, Any]] = {}
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._stashes: Dict[str, Dict[str, Any]] = {}
        self._stats: Dict[str, Any] = {}
        self._revision = 0
        self._durations: Dict[str, float] = {}
        self._rate: Dict[str, Dict[str, Any]] = {}
        self._idem: Dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def load_songs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        docs = [dict(doc) for doc in self._songs.values()]
        if limit is not None and limit > 0:
            docs = docs[-limit:]
        return docs

    def count_songs(self) -> int:
        return len(self._songs)

    def commit_songs(self, songs: List[Dict[str, Any]], build: Dict[str, Any]) -> int:
        changed = 0
        for song in songs:
            video_id = song.get("video_id") or ""
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            doc = {
                "video_id": video_id,
                "track": song.get("track") or song.get("title", ""),
                "title": song.get("title", ""),
                "artist": song.get("artist", ""),
                "language": song.get("language", ""),
                "lyrics": song.get("lyrics", ""),
                "backend": song.get("backend") or "",
                "duration": song.get("duration"),
            }
            if self._songs.get(video_id) != doc:
                changed += 1
            self._songs[video_id] = doc
        if changed:
            self._revision += 1
        self._stats = dict(build)
        return changed

    def prune_songs(self, keep_ids: Iterable[str]) -> int:
        keep = set(keep_ids)
        drop = [v for v in self._songs if v not in keep]
        for video_id in drop:
            self._songs.pop(video_id, None)
        return len(drop)

    def cached_lyric_count(self) -> int:
        return len(self._cache)

    def cache_get(self, video_id: str) -> Optional[Dict[str, Any]]:
        doc = self._cache.get(video_id)
        if not doc or not (doc.get("lyrics") or "").strip():
            return None
        return dict(doc)

    def cache_put(self, song: Dict[str, Any]) -> None:
        if not (song.get("lyrics") or "").strip():
            return
        self._cache[song.get("video_id", "")] = dict(song, cached_at=_now())

    def failed_all(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._failed.items()}

    def failed_record(self, song: Dict[str, Any], reason: str, duration: Optional[float]) -> None:
        video_id = song.get("video_id", "")
        entry = self._failed.get(video_id, {})
        entry.update(
            video_id=video_id,
            title=song.get("track") or song.get("title", ""),
            artist=song.get("artist", ""),
            duration=duration,
            attempts=int(entry.get("attempts", 0)) + 1,
            reason=reason,
            last_try=_now(),
        )
        self._failed[video_id] = entry

    def failed_resolve(self, video_id: str) -> None:
        self._failed.pop(video_id, None)

    def failed_count(self) -> int:
        return len(self._failed)

    def job_put(self, job: Dict[str, Any]) -> None:
        job_id = job.get("job_id")
        if not job_id:
            return
        current = self._jobs.get(job_id, {})
        current.update({k: v for k, v in job.items() if v is not None})
        current.setdefault("created_at", _now())
        current["updated_at"] = _now()
        self._jobs[job_id] = current

    def job_get(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(job_id)
        return dict(job) if job else None

    def jobs_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        jobs = sorted(
            self._jobs.values(), key=lambda j: j.get("created_at", 0), reverse=True
        )
        return [dict(j) for j in jobs[:limit]]

    def jobs_pending(self) -> List[Dict[str, Any]]:
        return [
            dict(j)
            for j in self._jobs.values()
            if j.get("status") not in ("committed", "skipped")
        ]

    def stash_put(self, job_id: str, songs: List[Dict[str, Any]], stash: Dict[str, Any]) -> None:
        self._stashes[job_id] = {"job_id": job_id, "songs": songs, "stash": stash}

    def stashes(self) -> List[Dict[str, Any]]:
        return [dict(v) for v in self._stashes.values()]

    def stash_delete(self, job_id: str) -> None:
        self._stashes.pop(job_id, None)

    def stats_get(self) -> Dict[str, Any]:
        return dict(self._stats)

    def stats_revision(self) -> int:
        return self._revision

    def stats_put(self, build: Dict[str, Any]) -> None:
        self._stats = dict(build)

    def durations_all(self) -> Dict[str, float]:
        return dict(self._durations)

    def duration_put(self, video_id: str, duration: float) -> None:
        if video_id and duration:
            self._durations[video_id] = float(duration)

    def rate_limit_hit(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int, int]:
        now = _now()
        entry = self._rate.get(key)
        if not entry or entry.get("resetAt", 0) <= now:
            entry = {"count": 0, "resetAt": now + window_seconds}
        entry["count"] += 1
        self._rate[key] = entry
        return entry["count"] <= limit, entry["count"], int(entry["resetAt"] - now)

    def idempotent_job(self, key: str) -> Optional[str]:
        return self._idem.get(key)

    def remember_idempotent_job(self, key: str, job_id: str, ttl_days: int = 7) -> None:
        if key:
            self._idem[key] = job_id


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_STORE: Optional[Store] = None


def get_store() -> Store:
    global _STORE
    if _STORE is not None:
        return _STORE
    # One connection string. `MONGO_URI` is accepted as an alias for tools that
    # use that name, but MONGODB_URI always wins.
    uri = (os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or "").strip()
    if not uri:
        print(
            "[lirify] MONGODB_URI is not set; using the in-process MemoryStore. "
            "This is for local development only.",
            flush=True,
        )
        _STORE = MemoryStore()
        return _STORE
    db_name = (os.environ.get("MONGODB_DB") or "").strip()
    if not db_name:
        # Derive the database from the URI path, exactly like a Mongoose client.
        path = re.sub(r"^mongodb(?:\+srv)?://[^/]+/?", "", uri).split("?")[0]
        db_name = path or "lirify"
    try:
        _STORE = MongoStore(uri, db_name)
    except Exception as exc:  # pragma: no cover - DNS/auth/project problems
        # A bad URI must not stop the container: running degraded (empty index) is
        # recoverable and visible in /health, a crash loop is neither.
        message = f"{type(exc).__name__}: {exc}"
        print(
            f"[lirify] MongoDB unavailable ({redact_uri(uri)}): {message}. "
            "Serving with an empty in-memory index.",
            flush=True,
        )
        fallback = MemoryStore()
        fallback.init_error = message
        _STORE = fallback
    return _STORE


def reset_store() -> None:
    """Test helper: drop the cached singleton."""
    global _STORE
    _STORE = None


def new_job_id(prefix: str = "job") -> str:
    return f"{prefix}-{int(_now() * 1000)}-{uuid.uuid4().hex[:6]}"


def iso_timestamp(value: Optional[float] = None) -> str:
    return _iso(value if value is not None else _now())
