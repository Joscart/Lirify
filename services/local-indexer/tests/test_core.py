"""Tests for the core engine. No network, no model download, no database."""

import re
import sys
import types
import unittest
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# --- stubs: lingua and sentence-transformers are not importable offline ----
def _install_stubs():
    if "lingua" not in sys.modules:
        lingua = types.ModuleType("lingua")

        class _Language:
            def __init__(self, name):
                self.name = name

        class _Detector:
            def detect_language_of(self, text):
                low = text.lower()
                if re.search(r"\b(los|las|la|el|de|y|que|con)\b", low):
                    return _Language("SPANISH")
                if re.search(r"\b(der|die|das|und|den)\b", low):
                    return _Language("GERMAN")
                if re.search(r"\b(le|les|des|et|une|pour)\b", low):
                    return _Language("FRENCH")
                if re.search(r"\b(i|w|z|na|się|jest)\b", low):
                    return _Language("POLISH")
                return _Language("ENGLISH")

        class _Builder:
            @classmethod
            def from_all_languages(cls):
                return cls()

            def build(self):
                return _Detector()

        lingua.LanguageDetectorBuilder = _Builder
        sys.modules["lingua"] = lingua

    if "sentence_transformers" not in sys.modules:
        st = types.ModuleType("sentence_transformers")

        class SentenceTransformer:
            def __init__(self, name):
                self.name = name
                self.dim = 64

            def encode(self, texts, convert_to_numpy=True):
                if isinstance(texts, str):
                    texts = [texts]
                out = np.zeros((len(texts), self.dim), dtype=np.float32)
                for row, text in enumerate(texts):
                    for word in re.findall(r"[^\W\d_]+", text.lower()):
                        out[row, zlib.crc32(word.encode()) % self.dim] += 1.0
                return out

        st.SentenceTransformer = SentenceTransformer
        sys.modules["sentence_transformers"] = st


_install_stubs()

import core

DOCS = [
    {
        "video_id": "aaaaaaaaaaa",
        "track": "Amor de verano",
        "artist": "Sol",
        "language": "es",
        "lyrics": "el amor de verano vuelve cada año con el sol y la playa",
        "backend": "lrclib",
    },
    {
        "video_id": "bbbbbbbbbbb",
        "track": "Winter Love",
        "artist": "North",
        "language": "en",
        "lyrics": "winter love is cold and the snow keeps falling on the road",
        "backend": "lrclib",
    },
    {
        "video_id": "ccccccccccc",
        "track": "Sommer Sonne",
        "artist": "Nord",
        "language": "de",
        "lyrics": "die sonne und das meer im sommer sind warm und hell",
        "backend": "netease",
    },
]


def make_indexer():
    return core.Indexer(dimension_embeddings=64)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.indexer = make_indexer()

    def test_procesar_texto_returns_flat_list(self):
        terms = self.indexer.procesar_texto(
            "el amor de verano con el sol\nwinter love is cold and snow"
        )
        self.assertIsInstance(terms, list)
        self.assertTrue(terms)
        self.assertTrue(all(isinstance(term, str) for term in terms))
        self.assertIn("amor", terms)
        self.assertIn("winter", terms)

    def test_unsupported_language_is_still_indexed(self):
        terms = self.indexer.procesar_texto("to jest polski tekst o miłości i życie")
        self.assertTrue(terms)
        self.assertIn("polski", terms)

    def test_empty_text_is_ignored(self):
        self.assertIsNone(self.indexer.procesar_texto(""))
        self.assertIsNone(self.indexer.agregar_documento(""))

    def test_metadata_is_stored(self):
        self.indexer.indexar_canciones(DOCS)
        self.assertEqual(self.indexer.ids[0], "aaaaaaaaaaa")
        self.assertEqual(self.indexer.titulos[0], "Amor de verano")
        self.assertEqual(self.indexer.artistas[0], "Sol")
        self.assertEqual(self.indexer.idiomas[0], "es")
        self.assertEqual(self.indexer.backends[1], "lrclib")


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.indexer = make_indexer()
        self.indexer.indexar_canciones(DOCS)

    def test_matrix_shape_matches_documents(self):
        matrix = self.indexer.matriz_embeddings_llm
        self.assertIsNotNone(matrix)
        self.assertEqual(matrix.shape, (3, 64))
        self.assertEqual(matrix.dtype, np.float32)

    def test_incremental_indexing_appends_rows(self):
        indexer = make_indexer()
        indexer.indexar_canciones(DOCS[:2])
        self.assertEqual(indexer.matriz_embeddings_llm.shape, (2, 64))
        indexer.indexar_canciones(DOCS[2:])
        self.assertEqual(indexer.matriz_embeddings_llm.shape, (3, 64))

    def test_duplicate_video_ids_are_skipped(self):
        indexer = make_indexer()
        first = indexer.indexar_canciones(DOCS)
        second = indexer.indexar_canciones(DOCS)
        self.assertEqual(len(first), 3)
        self.assertEqual(second, [])
        self.assertEqual(indexer.estadisticas()["songs_indexed"], 3)

    def test_empty_index_builds_empty_matrix(self):
        empty = make_indexer()
        matrix = empty.construir_matriz_embeddings_llm()
        self.assertEqual(matrix.shape[0], 0)

    def test_search_ranks_semantically_closest_first(self):
        payload = self.indexer.buscar("winter snow", limite=3)
        self.assertEqual(payload["engine"], "embeddings")
        self.assertTrue(payload["results"])
        self.assertEqual(payload["results"][0]["video_id"], "bbbbbbbbbbb")
        scores = [row["score"] for row in payload["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_search_respects_limit_and_metadata_boost(self):
        payload = self.indexer.buscar("Sommer Sonne", limite=1)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["video_id"], "ccccccccccc")

    def test_empty_query_returns_no_results(self):
        self.assertEqual(self.indexer.buscar("")["results"], [])

    def test_recommend_excludes_seeds(self):
        payload = self.indexer.recomendar(["aaaaaaaaaaa"], limite=2)
        self.assertEqual(payload["seed_video_id"], "aaaaaaaaaaa")
        self.assertTrue(payload["recommendations"])
        ids = [row["video_id"] for row in payload["recommendations"]]
        self.assertNotIn("aaaaaaaaaaa", ids)
        self.assertIn(payload["engine"], {"embeddings", "none"})

    def test_recommend_unknown_seed_is_empty(self):
        payload = self.indexer.recomendar(["zzzzzzzzzzz"], limite=2)
        self.assertEqual(payload["recommendations"], [])

    def test_statistics_are_consistent(self):
        stats = self.indexer.estadisticas()
        self.assertEqual(stats["songs_indexed"], 3)
        self.assertEqual(stats["video_ids"], 3)
        self.assertGreater(stats["vocabulary_size"], 0)
        self.assertEqual(stats["embedding_dim"], 64)
        self.assertIn("es", stats["languages"])


class SerializationTests(unittest.TestCase):
    def setUp(self):
        self.indexer = make_indexer()
        self.indexer.indexar_canciones(DOCS)

    def test_roundtrip_dict_keeps_documents_and_search(self):
        payload = self.indexer.a_diccionario(incluir_embeddings=True)
        restored = make_indexer()
        restored.desde_diccionario(payload)
        self.assertEqual(restored.estadisticas()["songs_indexed"], 3)
        self.assertEqual(restored.ids[:3], self.indexer.ids)
        self.assertIsNotNone(restored.matriz_embeddings_llm)
        result = restored.buscar("winter snow", limite=3)
        self.assertEqual(result["results"][0]["video_id"], "bbbbbbbbbbb")

    def test_roundtrip_without_embeddings(self):
        payload = self.indexer.a_diccionario(incluir_embeddings=False)
        restored = make_indexer()
        restored.desde_diccionario(payload)
        self.assertIsNone(restored.matriz_embeddings_llm)
        self.assertEqual(restored.vocabulary, self.indexer.vocabulary)


class PublicacionTests(unittest.TestCase):
    def setUp(self):
        self.indexer = make_indexer()
        self.indexer.indexar_canciones(DOCS)

    def test_mongo_documents_use_camel_case_and_no_matrices(self):
        documents = self.indexer._documentos_mongo()
        self.assertEqual(len(documents), 3)
        first = documents[0]
        self.assertEqual(first["videoId"], "aaaaaaaaaaa")
        self.assertIn("lyrics", first)
        self.assertIn("schemaVersion", first)
        self.assertNotIn("matrices", first)
        self.assertNotIn("tfidf", first)

    def test_qdrant_points_only_carry_vectors_and_metadata(self):
        points = self.indexer._puntos_qdrant()
        self.assertEqual(len(points), 3)
        self.assertEqual(len(points[0]["vector"]), 64)
        self.assertEqual(
            set(points[0]["payload"]),
            {"video_id", "title", "artist", "language"},
        )
        self.assertNotIn("lyrics", points[0]["payload"])

    def test_publicar_writes_songs_embeddings_and_scalar_stats(self):
        captured = {}
        fake = _fake_cloud(captured)
        previous = {name: sys.modules.get(name) for name in ("pymongo", "requests")}
        sys.modules["pymongo"] = fake["pymongo"]
        sys.modules["requests"] = fake["requests"]
        try:
            payload = self.indexer.publicar(
                mongo_uri="mongodb://fake",
                db_name="lirify",
                qdrant_url="http://qdrant",
                coleccion="lirify_lyrics_qwen3",
            )
        finally:
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.assertTrue(payload["published"])
        self.assertEqual(
            {args[0] for args, _ in captured["indexes"]}, {"videoId", "language"}
        )
        self.assertEqual(payload["songs"], 3)
        self.assertEqual(payload["vectors"], 3)
        self.assertEqual(payload["revision"], 4)

        stats_update = captured["stats_update"]
        build = stats_update["$set"]["build"]
        self.assertNotIn("matrices", build)
        self.assertEqual(build["songs_indexed"], 3)
        self.assertEqual(build["embedding_dim"], 64)
        for point in captured["qdrant_points"]:
            self.assertEqual(len(point["vector"]), 64)


def _fake_cloud(captured):
    class _Result:
        upserted_count = 3
        modified_count = 0

    class _Songs:
        def create_index(self, *args, **kwargs):
            captured.setdefault("indexes", []).append((args, kwargs))

        def bulk_write(self, operations, ordered=False):
            captured["songs_ops"] = operations
            return _Result()

    class _Stats:
        revision = 3

        def update_one(self, selector, update, upsert=False):
            captured["stats_update"] = update
            self.revision += int(update.get("$inc", {}).get("revision", 0))

        def find_one(self, selector):
            return {"_id": "global", "revision": self.revision}

    class _Database(dict):
        def __init__(self):
            super().__init__()
            self["songs"] = _Songs()
            self["index_stats"] = _Stats()

        def __getitem__(self, name):
            return dict.__getitem__(self, name)

    class MongoClient:
        def __init__(self, *args, **kwargs):
            self.database = _Database()

        def __getitem__(self, name):
            return self.database

        def close(self):
            pass

    class UpdateOne:
        def __init__(self, selector, update, upsert=False):
            self.selector = selector
            self.update = update
            self.upsert = upsert

    pymongo = types.ModuleType("pymongo")
    pymongo.MongoClient = MongoClient
    pymongo.UpdateOne = UpdateOne

    class _Response:
        def __init__(self, status_code=200, text=""):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {}

    def _get(url, headers=None, timeout=None):
        return _Response(200)

    def _put(url, headers=None, json=None, timeout=None):
        if url.endswith("/points?wait=true"):
            captured.setdefault("qdrant_points", []).extend(json["points"])
        return _Response(200)

    requests = types.ModuleType("requests")
    requests.get = _get
    requests.put = _put
    requests.RequestException = Exception

    return {"pymongo": pymongo, "requests": requests}


if __name__ == "__main__":
    unittest.main(verbosity=2)
