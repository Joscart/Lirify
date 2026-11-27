"""TF-IDF cosine retrieval for the UPSpotify search page."""

from typing import Any

import numpy as np

RESULT_LIMIT = 10
RECOMMENDATION_LIMIT = 3

ScoredSong = tuple[int, float]


def rank_catalogue(
    state: dict[str, Any], query_tokens: dict[str, list[str]]
) -> list[tuple[int, float, list[ScoredSong]]]:
    songs = state["songs"]
    tfidf = state.get("tfidf")
    if not songs or tfidf is None:
        return []

    positions = {term: row for row, term in enumerate(state["vocab"])}
    document_frequency = state["doc_freq"]
    scores = np.zeros(len(songs), dtype=np.float32)
    for language, tokens in query_tokens.items():
        rows, counts = np.unique(
            [positions[token] for token in tokens if token in positions], return_counts=True
        )
        if not rows.size:
            continue
        weights = (1 + np.log10(counts)) * np.log10(len(songs) / document_frequency[rows])
        norm = np.linalg.norm(weights)
        if not norm:
            continue
        columns = [i for i, song in enumerate(songs) if song["language"] == language]
        scores[columns] = (weights / norm) @ tfidf[np.ix_(rows, columns)]

    ids = [song["video_id"] for song in songs]
    top = sorted(np.flatnonzero(scores > 0), key=lambda i: (-scores[i], ids[i]))[:RESULT_LIMIT]
    excluded = set(top)
    candidates = [i for i in range(len(songs)) if i not in excluded]
    similarities = state["matrices"]["lyrics"]

    def score(value: float) -> float:
        # Float32 matrix products can round a perfect cosine slightly above 1.
        return min(1.0, max(0.0, float(value)))

    ranked = []
    for index in top:
        neighbours = similarities[index]
        best = sorted(candidates, key=lambda i: (-neighbours[i], ids[i]))[:RECOMMENDATION_LIMIT]
        ranked.append((index, score(scores[index]), [(i, score(neighbours[i])) for i in best]))
    return ranked
