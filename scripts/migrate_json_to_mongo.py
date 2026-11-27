#!/usr/bin/env python3
"""Import the legacy `data/*.json` files into MongoDB Atlas (or the local Mongo).

The stateless backend never reads these files, so this is the one-time bridge
from the old on-disk index to the database it now uses.

    # from the repository root, using the running api image (no host deps):
    docker compose run --rm --no-deps \
      -v "$PWD/scripts:/scripts:ro" -v "$PWD/data:/legacy:ro" \
      api python /scripts/migrate_json_to_mongo.py --data-dir /legacy

    # or from a host with pymongo installed:
    python3 scripts/migrate_json_to_mongo.py --data-dir data

It is idempotent (upserts keyed by videoId) and additive: no document is deleted.
Matrices, the inverted index and video_ids are intentionally NOT imported — they
are derived (in memory for small indexes, Qdrant for large ones).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = 1


def load_env(path: Path) -> None:
    """Minimal .env loader so the script works outside docker compose too."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def db_name_from_uri(uri: str, fallback: str = "lirify") -> str:
    match = re.match(r"^mongodb(?:\+srv)?://[^/]+/([^?]*)", uri)
    if match and match.group(1):
        return match.group(1)
    return fallback


def redact(uri: str) -> str:
    match = re.match(
        r"^(mongodb(?:\+srv)?)://(?:([^:@/]+)(?::[^@/]*)?@)?([^/?]+)(?:/([^?]*))?", uri
    )
    if not match:
        return "<invalid uri>"
    scheme, user, host, database = match.groups()
    return f"{scheme}://{user + '@' if user else ''}{host}/{database or ''}"


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def song_update(song: Dict[str, Any], now: float, insert_only: bool) -> Optional[Dict[str, Any]]:
    video_id = song.get("video_id") or ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or not (song.get("lyrics") or "").strip():
        return None
    fields = {
        "videoId": video_id,
        "title": song.get("title") or "",
        "youtubeTitle": song.get("youtube_title") or song.get("title") or "",
        "artist": song.get("artist") or "",
        "language": song.get("language") or "unknown",
        "lyrics": song.get("lyrics") or "",
        "backend": song.get("backend") or "",
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": now,
    }
    if insert_only:
        return {"$setOnInsert": {**fields, "createdAt": now}}
    return {"$set": fields, "$setOnInsert": {"createdAt": now}}


def migrate(data_dir: Path, dry_run: bool, limit: Optional[int], seed_local: bool = False) -> Dict[str, int]:
    from pymongo import MongoClient, UpdateOne

    uri = (os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or "").strip()
    if not uri:
        raise SystemExit("MONGODB_URI is not set (export it or add it to .env)")

    database = os.environ.get("MONGODB_DB") or db_name_from_uri(uri)
    if seed_local:
        from pymongo.uri_parser import parse_uri

        if parse_uri(uri)["nodelist"] != [("mongo", 27017)]:
            raise SystemExit("Local catalogue seed requires the Compose mongo service")
        if not dry_run:
            from store import MongoStore

            schema = MongoStore(uri, database)
            if schema.init_error:
                raise SystemExit("Could not initialize the local database schema")
            schema.client.close()
    print(f"target: {redact(uri)} db={database} dry_run={dry_run}")
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    client.admin.command("ping")
    db = client[database]
    now = time.time()
    counts: Dict[str, int] = {}

    # --- songs -------------------------------------------------------------
    songs_path = data_dir / "songs.json"
    if songs_path.exists():
        songs = read_json(songs_path)
        if limit:
            songs = songs[:limit]
        ops = []
        for song in songs:
            update = song_update(song, now, seed_local)
            if update is not None:
                ops.append(UpdateOne({"videoId": song["video_id"]}, update, upsert=True))
        if ops and not dry_run:
            result = db["songs"].bulk_write(ops, ordered=False)
            counts["songs"] = int(result.upserted_count + result.modified_count)
            if counts["songs"]:
                # Tell running replicas (Cloud Run) that their in-memory index is
                # stale; they reload within INDEX_REFRESH_SECONDS.
                db["index_stats"].update_one(
                    {"_id": "global"}, {"$inc": {"revision": 1}}, upsert=True
                )
        else:
            counts["songs"] = len(ops)
        print(f"songs:        {counts['songs']} {'would be ' if dry_run else ''}upserted")

    if seed_local:
        client.close()
        return counts

    # --- lyric cache -------------------------------------------------------
    cache_dir = data_dir / "cache" / "lyrics"
    if cache_dir.is_dir():
        ops = []
        for path in sorted(cache_dir.glob("*.json")):
            try:
                doc = read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            video_id = doc.get("video_id") or path.stem
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            if not (doc.get("lyrics") or "").strip():
                continue
            ops.append(
                UpdateOne(
                    {"videoId": video_id},
                    {
                        "$set": {
                            "videoId": video_id,
                            "title": doc.get("track") or doc.get("title") or "",
                            "youtubeTitle": doc.get("title") or "",
                            "artist": doc.get("artist") or "",
                            "language": doc.get("language") or "",
                            "lyrics": doc.get("lyrics") or "",
                            "backend": doc.get("backend") or "",
                            "cachedAt": doc.get("cached_at") or now,
                            "schemaVersion": SCHEMA_VERSION,
                        }
                    },
                    upsert=True,
                )
            )
        if ops and not dry_run:
            result = db["lyrics_cache"].bulk_write(ops, ordered=False)
            counts["lyrics_cache"] = int(result.upserted_count + result.modified_count)
        else:
            counts["lyrics_cache"] = len(ops)
        print(f"lyrics_cache: {counts['lyrics_cache']} {'would be ' if dry_run else ''}upserted")

    # --- failed songs ------------------------------------------------------
    failed_path = data_dir / "failed_songs.json"
    if failed_path.exists():
        failed = read_json(failed_path)
        ops = []
        for video_id, entry in (failed or {}).items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            ops.append(
                UpdateOne(
                    {"videoId": video_id},
                    {
                        "$set": {
                            "videoId": video_id,
                            "title": entry.get("title") or "",
                            "artist": entry.get("artist") or "",
                            "duration": entry.get("duration"),
                            "attempts": int(entry.get("attempts") or 0),
                            "reason": entry.get("reason") or "no lyrics",
                            "lastTry": entry.get("last_try") or now,
                            "schemaVersion": SCHEMA_VERSION,
                        }
                    },
                    upsert=True,
                )
            )
        if ops and not dry_run:
            result = db["failed_songs"].bulk_write(ops, ordered=False)
            counts["failed_songs"] = int(result.upserted_count + result.modified_count)
        else:
            counts["failed_songs"] = len(ops)
        print(f"failed_songs: {counts['failed_songs']} {'would be ' if dry_run else ''}upserted")

    # --- media durations ---------------------------------------------------
    media_path = data_dir / "ui_media.json"
    if media_path.exists():
        durations = (read_json(media_path) or {}).get("durations") or {}
        ops = [
            UpdateOne(
                {"videoId": video_id},
                {"$set": {"videoId": video_id, "duration": float(value), "updatedAt": now}},
                upsert=True,
            )
            for video_id, value in durations.items()
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
        ]
        if ops and not dry_run:
            result = db["media_durations"].bulk_write(ops, ordered=False)
            counts["media_durations"] = int(result.upserted_count + result.modified_count)
        else:
            counts["media_durations"] = len(ops)
        print(f"durations:    {counts['media_durations']} {'would be ' if dry_run else ''}upserted")

    # --- intentionally skipped --------------------------------------------
    print("\nnot imported (derived, by design):")
    for name in ("matrices.json", "inverted_index.json", "video_ids.json", "queue_state.json"):
        if (data_dir / name).exists():
            print(f"  {name}")
    print("  matrices -> rebuilt in memory (small index) / Qdrant (large index)")

    if not dry_run:
        print("\ncollection counts now:")
        for name in ("songs", "lyrics_cache", "failed_songs", "media_durations", "jobs"):
            print(f"  {name}: {db[name].count_documents({})}")
        print(
            "\nrestart the api so it rebuilds the index and backfills Qdrant:\n"
            "  docker compose restart api"
        )
    client.close()
    return counts


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default="data", help="Legacy data directory (default: ./data)")
    parser.add_argument("--env-file", default=".env", help="File to read MONGODB_URI from if unset")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Import at most N songs (testing)")
    parser.add_argument("--seed-local", action="store_true", help="Insert missing catalogue songs in Compose MongoDB only; preserve existing songs")
    args = parser.parse_args(list(argv) if argv else None)

    root = Path(__file__).resolve().parent.parent
    load_env(Path(args.env_file) if Path(args.env_file).is_absolute() else root / args.env_file)
    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        raise SystemExit(f"data directory not found: {data_dir}")
    migrate(data_dir, args.dry_run, args.limit, args.seed_local)
    return 0


if __name__ == "__main__":
    sys.exit(main())
