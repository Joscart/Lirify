#!/usr/bin/env python3
"""Verify Cloudflare Workers AI Qwen3-Embedding-0.6B and compare embeddings.

Usage:
    export CLOUDFLARE_ACCOUNT_ID=...
    export CLOUDFLARE_API_TOKEN=...     # Workers AI: Read
    scripts/local/verify_cloudflare_embed.py "amor de verano" "winter love"

The model name defaults to @cf/qwen/qwen3-embedding-0.6b; override with
CF_EMBED_MODEL. The script prints the vector size, the equivalent curl command,
and the cosine similarity matrix so you can confirm the API returns usable,
normalised vectors before pointing python-backend at it.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request

DEFAULT_MODEL = "@cf/qwen/qwen3-embedding-0.6b"
DEFAULT_TEXTS = [
    "amor de verano en la playa",
    "winter love and cold snow",
    "cancion de verano con sol",
]


def _env(*names: str) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    na = math.sqrt(sum(a * a for a in left))
    nb = math.sqrt(sum(b * b for b in right))
    return dot / (na * nb) if na and nb else 0.0


def _extract_vectors(payload: dict) -> list[list[float]]:
    if payload.get("success") is False:
        raise RuntimeError(
            str(payload.get("errors") or "Cloudflare returned success=false")
        )
    result = payload.get("result")
    if isinstance(result, list):
        data = result
    else:
        result = result or {}
        data = (
            result.get("data")
            or result.get("embeddings")
            or result.get("response")
            or payload.get("data")
            or payload.get("embeddings")
        )
    if isinstance(data, dict):
        data = data.get("data") or data.get("embeddings")
    if not data:
        raise RuntimeError(f"no vectors in response: {json.dumps(payload)[:400]}")
    if isinstance(data[0], (int, float)):
        data = [data]
    return [[float(value) for value in row] for row in data]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("texts", nargs="*", default=DEFAULT_TEXTS)
    parser.add_argument(
        "--model", default=os.environ.get("CF_EMBED_MODEL", DEFAULT_MODEL)
    )
    args = parser.parse_args()

    account = _env("CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID")
    token = _env("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "CLOUDFLARE_API_KEY")
    if not account or not token:
        print(
            "Missing credentials. Export CLOUDFLARE_ACCOUNT_ID and "
            "CLOUDFLARE_API_TOKEN (Workers AI: Read), then retry.",
            file=sys.stderr,
        )
        return 2

    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{args.model}"
    print("model:", args.model)
    print("url:  ", url)
    print(
        "curl:  curl -sS "
        f"https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/ai/run/{args.model} "
        "-X POST -H 'Authorization: Bearer $CLOUDFLARE_API_TOKEN' "
        f"-H 'Content-Type: application/json' -d '{json.dumps({'text': args.texts})}'"
    )

    request = urllib.request.Request(
        url,
        data=json.dumps({"text": args.texts}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"network error: {exc.reason}", file=sys.stderr)
        return 1

    try:
        vectors = _extract_vectors(payload)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    dims = {len(vector) for vector in vectors}
    print(f"vectors: {len(vectors)}  dims: {sorted(dims)}")
    if len(dims) != 1:
        print("ERROR: inconsistent vector sizes", file=sys.stderr)
        return 1

    expected = int(os.environ.get("EMBEDDING_DIM", "1024"))
    dim = dims.pop()
    if dim != expected:
        print(
            f"WARNING: {dim} != EMBEDDING_DIM {expected}; Qdrant search would fail "
            "(query and document vectors must share one space).",
            file=sys.stderr,
        )

    print("\ncosine similarity:")
    for i, left in enumerate(vectors):
        row = " ".join(f"{_cosine(left, right):+.4f}" for right in vectors)
        print(f"  [{i}] {row}")
    print("\nfirst vector preview:", [round(value, 5) for value in vectors[0][:8]])
    return 0 if dim == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
