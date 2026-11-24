"""Qwen3-Embedding tokenizer for the local vocabulary and Jaccard signal.

The local indexer must build its vocabulary and inverted index with the *exact*
tokenizer of the embedding model, otherwise the terms it persists do not line up
with the llama.cpp embeddings. This module is the single loader for
``Qwen/Qwen3-Embedding-0.6B`` and degrades gracefully:

1. ``QWEN3_TOKENIZER_PATH`` points at ``tokenizer.json`` (or the directory that
   contains it). This is what the local indexer mounts into the container.
2. Otherwise ``transformers.AutoTokenizer.from_pretrained(QWEN3_TOKENIZER_ID)``.
3. Otherwise ``tokenizers.Tokenizer.from_pretrained(QWEN3_TOKENIZER_ID)``.
4. Otherwise the module reports ``fallback`` and callers keep the legacy
   whitespace/stem tokenizer, so the serving image still boots without the model
   assets (and without network access).

Nothing here downloads model weights: only the tokenizer assets, and only when a
path or the optional libraries are present.
"""

from __future__ import annotations

import os
import re
import threading
from typing import List, Optional, Set

TOKENIZER_ID = (os.environ.get("QWEN3_TOKENIZER_ID") or "Qwen/Qwen3-Embedding-0.6B").strip()
TOKENIZER_PATH = (os.environ.get("QWEN3_TOKENIZER_PATH") or "").strip()
ENABLED = (os.environ.get("QWEN3_TOKENIZER_ENABLED") or "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# Qwen3 uses ChatML markers; they are structural, never vocabulary terms.
_SPECIAL_RE = re.compile(r"^<\|.*\|>$")
# Byte-level BPE marks a leading space with U+0120 and a newline with U+010A.
_BYTE_LEVEL_RE = re.compile(r"[\u0120\u010a]")
_ALNUM_RE = re.compile(r"[0-9A-Za-z\u00c0-\u024f]")

_LOCK = threading.Lock()
_LOADED = False
_BACKEND = "fallback"
_TOKENIZER = None


def _candidate_file() -> Optional[str]:
    if not TOKENIZER_PATH:
        return None
    if os.path.isdir(TOKENIZER_PATH):
        candidate = os.path.join(TOKENIZER_PATH, "tokenizer.json")
        return candidate if os.path.isfile(candidate) else None
    if os.path.isfile(TOKENIZER_PATH):
        return TOKENIZER_PATH
    return None


def _load() -> None:
    global _LOADED, _BACKEND, _TOKENIZER
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        _LOADED = True
        if not ENABLED:
            print("[lirify] Qwen3 tokenizer disabled (QWEN3_TOKENIZER_ENABLED=0)", flush=True)
            return
        path = _candidate_file()
        if path:
            try:
                from tokenizers import Tokenizer

                _TOKENIZER = Tokenizer.from_file(path)
                _BACKEND = "tokenizers"
                print(f"[lirify] Qwen3 tokenizer loaded from {path}", flush=True)
                return
            except Exception as exc:  # pragma: no cover - optional dependency
                print(f"[lirify] Qwen3 tokenizer file failed ({path}): {exc}", flush=True)
        try:
            from transformers import AutoTokenizer

            _TOKENIZER = AutoTokenizer.from_pretrained(TOKENIZER_ID)
            _BACKEND = "transformers"
            print(f"[lirify] Qwen3 tokenizer loaded via transformers ({TOKENIZER_ID})", flush=True)
            return
        except Exception as exc:  # pragma: no cover - optional dependency
            print(f"[lirify] transformers tokenizer unavailable: {exc}", flush=True)
        try:
            from tokenizers import Tokenizer

            _TOKENIZER = Tokenizer.from_pretrained(TOKENIZER_ID)
            _BACKEND = "tokenizers"
            print(f"[lirify] Qwen3 tokenizer loaded via tokenizers ({TOKENIZER_ID})", flush=True)
            return
        except Exception as exc:  # pragma: no cover - optional dependency
            print(
                "[lirify] Qwen3 tokenizer unavailable; falling back to the legacy "
                f"whitespace/stem tokenizer ({exc})",
                flush=True,
            )
            _TOKENIZER = None
            _BACKEND = "fallback"


def available() -> bool:
    _load()
    return _TOKENIZER is not None


def backend() -> str:
    """"tokenizers" | "transformers" | "fallback"."""
    _load()
    return _BACKEND


def _clean(token: str) -> Optional[str]:
    token = _BYTE_LEVEL_RE.sub(" ", token).strip().lower()
    if not token or _SPECIAL_RE.match(token):
        return None
    if not _ALNUM_RE.search(token):
        return None
    return token


def tokenize_terms(text: str) -> List[str]:
    """Subword terms in model order, or ``[]`` when the tokenizer is unavailable.

    Duplicates are preserved so callers can build term frequencies; callers that
    need a set use :func:`token_set`.
    """
    _load()
    if _TOKENIZER is None or not text:
        return []
    try:
        if _BACKEND == "transformers":
            ids = _TOKENIZER.encode(text, add_special_tokens=False)
            raw = _TOKENIZER.convert_ids_to_tokens(ids)
        else:
            raw = _TOKENIZER.encode(text).tokens
    except Exception as exc:  # pragma: no cover - model assets changed
        print(f"[lirify] Qwen3 tokenization failed: {exc}", flush=True)
        return []
    terms: List[str] = []
    for token in raw:
        cleaned = _clean(token)
        if cleaned:
            terms.append(cleaned)
    return terms


def token_set(text: str, ngrams: int = 1) -> Set[str]:
    """Token-set used by the Jaccard signal; optional bigrams/trigrams.

    Qwen3 is byte-level BPE, so the *terms* are subwords. Bigrams are joined with
    ``\x1f`` so they can never collide with a unigram.
    """
    terms = tokenize_terms(text)
    if not terms:
        return set()
    if ngrams <= 1:
        return set(terms)
    out: Set[str] = set()
    for size in range(1, ngrams + 1):
        if size == 1:
            out.update(terms)
            continue
        for start in range(0, len(terms) - size + 1):
            out.add("\x1f".join(terms[start : start + size]))
    return out


def reset_tokenizer() -> None:
    """Test helper: drop the cached tokenizer."""
    global _LOADED, _TOKENIZER, _BACKEND
    with _LOCK:
        _LOADED = False
        _TOKENIZER = None
        _BACKEND = "fallback"
