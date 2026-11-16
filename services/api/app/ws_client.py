"""Example Python client for the Lirify live progress WebSocket.

Usage:
    python ws_client.py "https://youtu.be/VIDEO_ID" index
    python ws_client.py "https://www.youtube.com/playlist?list=..." extract
"""

import asyncio
import json
import sys

import websockets

WS_URL = "ws://localhost:8000/ws"


async def main(url: str, action: str, limit: int | None = None) -> None:
    job_id = f"py-{action}-{int(asyncio.get_running_loop().time() * 1000)}"
    async with websockets.connect(WS_URL, ping_interval=20) as ws:
        ready = json.loads(await ws.recv())
        print("connected:", ready.get("message"), "| indexed:", ready.get("indexed_songs"))
        urls = [part.strip() for part in url.split(",") if part.strip()]
        await ws.send(
            json.dumps(
                {
                    "action": action,
                    "url": urls[0] if urls else url,
                    "urls": urls if action == "queue" else None,
                    "limit": limit,
                    "job_id": job_id,
                }
            )
        )
        follow = {job_id}
        remaining = None
        async for raw in ws:
            event = json.loads(raw)
            kind = event.get("event")
            if kind == "queued_batch":
                follow.update(event.get("jobs") or [])
                remaining = len(event.get("jobs") or [])
                print(f"queued {remaining} playlists: {event.get('jobs')}")
                continue
            if event.get("job_id") not in (None, *follow):
                continue
            if kind == "song":
                print(
                    f"[{event['index']}/{event['total']}] "
                    f"{event['artist']} - {event['title']} "
                    f"({event['language']}, {event.get('backend')})"
                )
            elif kind == "song_retry":
                print(
                    f"[retry {event['index']}/{event['total']}] "
                    f"{event['artist']} - {event['title']} -> {event.get('backend')}"
                )
            elif kind == "status":
                print(f"[status:{event.get('stage')}] {event.get('message')}")
            elif kind == "extracted":
                print(f"extracted {event['count']} ids")
            elif kind == "stashed":
                print(f"stashed {event['docs']} songs / {event['terms']} terms")
            elif kind == "filtered":
                print(f"filtered: kept {event['kept']}, skipped {event['skipped']}")
            elif kind == "skipped":
                print("skipped:", event.get("reason"))
            elif kind == "recovered":
                print("recovered:", event.get("message"))
            elif kind == "retry_scheduled":
                print(f"retry #{event.get('attempts')} in {event.get('delay')}s: {event.get('message')}")
            elif kind == "requeued":
                print(f"requeued (attempt {event.get('attempts')})")
            elif kind == "gave_up":
                print("gave up:", event.get("message"))
                if remaining is not None:
                    remaining -= 1
                    if remaining > 0:
                        continue
                break
            elif kind == "done":
                print("done:", json.dumps(event.get("stats", event), ensure_ascii=False))
                if remaining is not None:
                    remaining -= 1
                    if remaining > 0:
                        continue
                break
            elif kind == "error":
                print("error:", event.get("message"))
                break


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python ws_client.py <url> [index|extract] [limit]")
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "index", limit))
