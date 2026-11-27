#!/usr/bin/env python3
"""Smoke-test the local indexer with a real playlist over gRPC.

    scripts/local/verify_playlist.py --url "https://youtube.com/playlist?list=..." --limit 2

It extracts the video ids first (yt-dlp inside the indexer), then queues a small
batch, polls the job and prints the final index stats. Nothing is published unless
the indexer runs with PUBLISH_ON_INDEX=1 (the compose default).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api" / "app"))

import grpc
from lirifypb import lirify_pb2 as pb
from lirifypb import lirify_pb2_grpc as pb_grpc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="127.0.0.1:50052")
    parser.add_argument("--url", required=True)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    channel = grpc.insecure_channel(args.target)
    service = pb_grpc.LirifyServiceStub(channel)
    try:
        extracted = service.ExtractVideoIds(
            pb.ExtractVideoIdsRequest(playlist_url=args.url, limit=args.limit),
            timeout=120,
        )
        print(f"extract: {extracted.count} video id(s)")
        for video_id in list(extracted.video_ids)[:5]:
            print("  -", video_id)
        if not extracted.count:
            print("no video ids resolved", file=sys.stderr)
            return 1

        job = service.IndexPlaylist(
            pb.IndexPlaylistRequest(
                playlist_url=args.url,
                limit=args.limit,
                source="verify_playlist",
            )
        )
        print(f"job: {job.job_id} status={job.status}")

        deadline = time.time() + args.timeout
        last = None
        while time.time() < deadline:
            current = service.GetJob(
                pb.GetJobRequest(job_id=job.job_id), timeout=20
            ).job
            state = (current.status, current.stage, current.added)
            if state != last:
                print(
                    f"  status={current.status} stage={current.stage} added={current.added}"
                )
                last = state
            if current.status in {"committed", "skipped", "error"}:
                break
            time.sleep(3)

        if current.status == "error":
            print(
                f"job failed: [{current.error_code}] {current.error}",
                file=sys.stderr,
            )
            return 1

        stats = service.GetIndexStats(pb.GetIndexStatsRequest(), timeout=20)
        print(
            f"index: {stats.indexed_songs} songs, {stats.vocabulary_size} terms, "
            f"revision {stats.revision}, mode {stats.mode}"
        )
        return 0
    finally:
        channel.close()


if __name__ == "__main__":
    raise SystemExit(main())
