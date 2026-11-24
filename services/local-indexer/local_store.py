"""Local-only persistence for the Qwen3 vocabulary and full inverted index.

The laptop indexer is allowed exactly two durable local artefacts:

1. ``vocabulary.json`` — the subword vocabulary derived from the
   ``Qwen/Qwen3-Embedding-0.6B`` tokenizer (term -> integer term id).
2. ``inverted_index.json`` — term id -> song postings (video id -> positions).

Everything else (tracks, lyrics, jobs, embeddings) lives in MongoDB Atlas and
Qdrant Cloud. This module never writes a song dump or a local cache; it only
projects committed songs through the tokenizer into those two files.

Both files are rewritten atomically so a crash mid-publish cannot leave a
half-written index behind, and both carry the tokenizer id so a mismatched
vocabulary is detected instead of silently mixed.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

_LOCK = threading.Lock()
_INFO_CACHE: Dict[str, Any] = {"stamp": None, "info": None}


def _directory() -> str:
    return (os.environ.get("LOCAL_INDEX_DIR") or "local-index").strip() or "local-index"


def paths() -> Tuple[str, str]:
    directory = _directory()
    vocab = (os.environ.get("LOCAL_VOCAB_PATH") or "").strip() or os.path.join(
        directory, "vocabulary.json"
    )
    inverted = (
        os.environ.get("LOCAL_INVERTED_INDEX_PATH") or ""
    ).strip() or os.path.join(directory, "inverted_index.json")
    return vocab, inverted


def _write_json_atomic(path: str, payload: Dict[str, Any]) -> int:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=".lirify-", suffix=".json", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return os.path.getsize(path)


def rebuild(songs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rebuild both files from committed songs using the Qwen3 tokenizer.

    ``songs`` is the in-memory committed catalogue (Atlas is the source of truth;
    this never dumps it to disk). Returns a stats dict for the RPC response.
    """
    from main import lyrics_terms, qwen_tokenizer  # local import: avoid a cycle

    tokenizer_id = qwen_tokenizer.TOKENIZER_ID
    backend = qwen_tokenizer.backend()
    vocab: Dict[str, int] = {}
    postings: Dict[int, Dict[str, List[int]]] = {}
    documents = 0
    total_tokens = 0

    for song in songs:
        video_id = song.get("video_id") or ""
        if not video_id:
            continue
        terms = lyrics_terms(song.get("lyrics") or "", song.get("language") or "")
        if not terms:
            continue
        documents += 1
        total_tokens += len(terms)
        for position, term in enumerate(terms, start=1):
            term_id = vocab.get(term)
            if term_id is None:
                term_id = len(vocab)
                vocab[term] = term_id
                postings[term_id] = {"term": term, "postings": {}}
            postings[term_id]["postings"].setdefault(video_id, []).append(position)

    generated_at = int(time.time())
    vocab_payload = {
        "tokenizer": tokenizer_id,
        "tokenizer_backend": backend,
        "generated_at": generated_at,
        "documents": documents,
        "terms": vocab,
    }
    inverted_payload = {
        "tokenizer": tokenizer_id,
        "tokenizer_backend": backend,
        "generated_at": generated_at,
        "documents": documents,
        "tokens": total_tokens,
        "terms": {str(term_id): row for term_id, row in postings.items()},
    }

    vocab_path, inverted_path = paths()
    with _LOCK:
        vocab_bytes = _write_json_atomic(vocab_path, vocab_payload)
        inverted_bytes = _write_json_atomic(inverted_path, inverted_payload)
        _INFO_CACHE["stamp"] = None

    stats = {
        "documents": documents,
        "vocabulary_terms": len(vocab),
        "inverted_terms": len(postings),
        "tokens": total_tokens,
        "vocabulary_bytes": vocab_bytes,
        "inverted_index_bytes": inverted_bytes,
        "updated_at": generated_at,
        "directory": os.path.dirname(vocab_path) or _directory(),
        "vocabulary_path": vocab_path,
        "inverted_index_path": inverted_path,
        "tokenizer": tokenizer_id,
        "tokenizer_backend": backend,
    }
    print(
        f"[lirify] local index rebuilt: {documents} docs, {len(vocab)} terms, "
        f"{vocab_bytes + inverted_bytes} bytes",
        flush=True,
    )
    return stats


def _stat(path: str) -> Optional[Tuple[int, int]]:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return int(info.st_size), int(info.st_mtime)


def info() -> Dict[str, Any]:
    """Describe the local files without loading them when nothing changed."""
    from main import qwen_tokenizer
    from vector import EMBEDDING_PROVIDER

    vocab_path, inverted_path = paths()
    vocab_stat = _stat(vocab_path)
    inverted_stat = _stat(inverted_path)
    stamp = (vocab_stat, inverted_stat)
    if _INFO_CACHE["stamp"] == stamp and _INFO_CACHE["info"] is not None:
        return dict(_INFO_CACHE["info"])

    documents = 0
    vocab_terms = 0
    inverted_terms = 0
    updated_at = 0
    tokenizer_id = qwen_tokenizer.TOKENIZER_ID
    backend = qwen_tokenizer.backend()
    try:
        with open(vocab_path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        documents = int(payload.get("documents") or 0)
        vocab_terms = len(payload.get("terms") or {})
        tokenizer_id = payload.get("tokenizer") or tokenizer_id
        backend = payload.get("tokenizer_backend") or backend
        updated_at = int(payload.get("generated_at") or 0)
    except (OSError, ValueError):
        pass
    try:
        with open(inverted_path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        inverted_terms = len(payload.get("terms") or {})
        documents = documents or int(payload.get("documents") or 0)
        updated_at = updated_at or int(payload.get("generated_at") or 0)
    except (OSError, ValueError):
        pass

    result = {
        "directory": os.path.dirname(vocab_path) or _directory(),
        "tokenizer": tokenizer_id,
        "tokenizer_backend": backend,
        "embedding_provider": EMBEDDING_PROVIDER,
        "documents": documents,
        "vocabulary_terms": vocab_terms,
        "inverted_terms": inverted_terms,
        "vocabulary_bytes": vocab_stat[0] if vocab_stat else 0,
        "inverted_index_bytes": inverted_stat[0] if inverted_stat else 0,
        "updated_at": updated_at,
        "vocabulary_path": vocab_path,
        "inverted_index_path": inverted_path,
    }
    _INFO_CACHE["stamp"] = stamp
    _INFO_CACHE["info"] = result
    return dict(result)
