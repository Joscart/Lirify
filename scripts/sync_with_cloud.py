#!/usr/bin/env python3
"""Keep the local stack and the Cloud Run deployment in sync.

Both run against the same Atlas + Qdrant (see `.env`), so there is only one copy
of the data — the difference is each process's in-memory index snapshot.

    # what does each side currently serve?
    python3 scripts/sync_with_cloud.py parity

    # index a playlist from the local stack, then make Cloud Run reload now
    python3 scripts/sync_with_cloud.py index "https://www.youtube.com/playlist?list=..."

    # just ask the deployed service to re-read the shared database
    python3 scripts/sync_with_cloud.py reload

    # check every 10s until both sides report the same count
    python3 scripts/sync_with_cloud.py parity --wait 300

Cloud Run normally notices a new revision on its own (`INDEX_REFRESH_SECONDS`,
default 60s); `reload` makes it immediate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOCAL_DEFAULT = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request(method: str, url: str, key: str = "", payload: dict | None = None, timeout: int = 120):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw}


def stats(base: str) -> dict:
    status, body = request("GET", f"{base.rstrip('/')}/health", timeout=30)
    if status != 200:
        return {"reachable": False, "http": status, "detail": str(body)[:200]}
    storage = body.get("storage") or {}
    return {
        "reachable": True,
        "indexed": body.get("indexed_songs", 0),
        "catalog": storage.get("catalog_songs"),
        "cap": storage.get("max_indexed_songs"),
        "grpc": body.get("grpc"),
        "mongo": body.get("mongo"),
        "vectors": storage.get("vectors"),
    }


def show_parity(local_base: str, cloud_base: str) -> bool:
    local = stats(local_base)
    cloud = stats(cloud_base)
    print(f"local  {local_base}: {json.dumps(local)}")
    print(f"cloud  {cloud_base}: {json.dumps(cloud)}")
    if not (local.get("reachable") and cloud.get("reachable")):
        return False
    same = local.get("indexed") == cloud.get("indexed")
    print("PARITY" if same else "DIFFERENT", f"| local={local.get('indexed')} cloud={cloud.get('indexed')}")
    if not same and cloud.get("cap") not in (None, -1) and (cloud.get("catalog") or 0) > cloud["cap"]:
        print(
            f"hint: cloud cap is {cloud['cap']} while Atlas holds {cloud['catalog']} songs; "
            "raise MAX_INDEXED_SONGS (and TF_VAR_python_memory) or prune the catalogue.",
            file=sys.stderr,
        )
    return same


def submit_and_wait(local_base: str, playlist: str, key: str, limit: int | None, timeout: int) -> bool:
    payload = {"playlist_url": playlist, "source_bot": "local-sync"}
    if limit:
        payload["limit"] = limit
    status, body = request("POST", f"{local_base}/api/v1/bot/index-playlist", key, payload)
    job = (body or {}).get("job") or {}
    job_id = job.get("job_id")
    print(f"submit -> {status} job={job_id}")
    if status not in (200, 202) or not job_id:
        print(json.dumps(body)[:400], file=sys.stderr)
        return False

    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        _, snapshot = request("GET", f"{local_base}/api/v1/bot/jobs/{urllib.parse.quote(job_id)}", key)
        job = (snapshot or {}).get("job") or {}
        current = f"{job.get('status')}/{job.get('stage')}"
        if current != last:
            print(f"  {current} added={job.get('added', 0)}")
            last = current
        if job.get("status") in ("committed", "skipped", "error"):
            return job.get("status") == "committed"
        time.sleep(5)
    print("timed out waiting for the job", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["parity", "reload", "index"])
    parser.add_argument("target", nargs="?", help="Playlist URL for `index`")
    parser.add_argument("--local", default=LOCAL_DEFAULT)
    parser.add_argument(
        "--cloud",
        default=os.environ.get("LIRIFY_CLOUD_API_URL", ""),
        help="Cloud Run URL (default: $LIRIFY_CLOUD_API_URL)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--wait", type=int, default=0, help="parity: retry for N seconds")
    args = parser.parse_args(argv)

    key = (os.environ.get("BOT_INGEST_API_KEY") or "").strip()
    cloud = (args.cloud or "").rstrip("/")
    if not cloud:
        print("set --cloud or LIRIFY_CLOUD_API_URL", file=sys.stderr)
        return 2
    if not key:
        print("BOT_INGEST_API_KEY is not set (check .env)", file=sys.stderr)
        return 2

    if args.command == "parity":
        deadline = time.time() + args.wait
        while True:
            same = show_parity(args.local, cloud)
            if same or time.time() >= deadline:
                return 0 if same else 1
            time.sleep(10)

    if args.command == "reload":
        status, body = request("POST", f"{cloud}/admin/reload", key)
        print(f"reload -> {status} {json.dumps(body)[:300]}")
        return 0 if status == 200 else 1

    if not args.target:
        print("index requires a playlist URL", file=sys.stderr)
        return 2
    if not submit_and_wait(args.local, args.target, key, args.limit, args.timeout):
        return 1
    status, body = request("POST", f"{cloud}/admin/reload", key)
    print(f"cloud reload -> {status} {json.dumps(body)[:300]}")
    return 0 if show_parity(args.local, cloud) else 1


if __name__ == "__main__":
    sys.exit(main())
