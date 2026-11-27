"""CRUD tests for db_admin/admin_api with in-memory fakes (no network)."""

import os
import re
import sys
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QDRANT_URL", "http://qdrant.test")
os.environ.setdefault("QDRANT_COLLECTION", "lirify_test")
os.environ.setdefault("MONGODB_URI", "mongodb://fake")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_core import _install_stubs

_install_stubs()

import core
import db_admin
from admin_api import build_app
from fastapi.testclient import TestClient


class FakePipeline:
    def __init__(self):
        self._lock = threading.RLock()
        self.indexer = core.Indexer(
            modelo_embeddings=_FakeModel(), dimension_embeddings=8
        )
        self.publicaciones = 0

    def reiniciar_indice(self):
        self.indexer.limpiar()
        return len(self.mongo.database["songs"].docs)

    def publicar(self, lote=64):
        self.publicaciones += 1
        return {
            "songs": len(self.indexer.docs_id),
            "vectors": len(self.indexer.docs_id),
            "revision": self.publicaciones,
        }


class _FakeModel:
    dim = 8

    def encode(self, texts, convert_to_numpy=True):
        import numpy as np

        if isinstance(texts, str):
            texts = [texts]
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"[^\W\d_]+", text.lower()):
                out[row, hash(word) % self.dim] += 1.0
        return out


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, field, direction):
        self.rows.sort(key=lambda row: row.get(field) or 0, reverse=direction < 0)
        return self

    def skip(self, value):
        self.rows = self.rows[value:]
        return self

    def limit(self, value):
        self.rows = self.rows[:value]
        return self

    def __iter__(self):
        return iter(self.rows)


class _Collection:
    def __init__(self):
        self.docs = {}

    def count_documents(self, filtro):
        return len(self._match(filtro))

    def _match(self, filtro):
        rows = list(self.docs.values())
        if not filtro:
            return rows
        if "$or" in filtro:
            patrones = [
                re.compile(item["$regex"], re.IGNORECASE) for item in filtro["$or"]
            ]
            return [
                row
                for row in rows
                if any(
                    patron.search(str(row.get(campo) or ""))
                    for patron in patrones
                    for campo in ("videoId", "title", "artist")
                )
            ]
        return [row for row in rows if all(row.get(k) == v for k, v in filtro.items())]

    def find(self, filtro=None, projection=None):
        return _Cursor([dict(row) for row in self._match(filtro or {})])

    def find_one(self, filtro, projection=None):
        rows = self._match(filtro)
        return dict(rows[0]) if rows else None

    def insert_one(self, doc):
        self.docs[doc["videoId"]] = dict(doc)

    def update_one(self, filtro, update, upsert=False):
        rows = self._match(filtro)
        if not rows:
            if not upsert:
                return _Result(0, 0, None)
            doc = {"videoId": filtro["videoId"]}
            doc.update(update.get("$set", {}))
            doc.update(update.get("$setOnInsert", {}))
            self.docs[doc["videoId"]] = doc
            return _Result(0, 0, doc["videoId"])
        rows[0].update(update.get("$set", {}))
        return _Result(1, 0, None)

    def delete_one(self, filtro):
        rows = self._match(filtro)
        if not rows:
            return _DeleteResult(0)
        del self.docs[rows[0]["videoId"]]
        return _DeleteResult(1)


class _Result:
    def __init__(self, matched, modified, upserted):
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_id = upserted
        self.deleted_count = 0


class _DeleteResult:
    def __init__(self, deleted):
        self.deleted_count = deleted


class _Database(dict):
    def __init__(self):
        super().__init__()
        self["songs"] = _Collection()
        self["index_stats"] = _Collection()


class _FakeMongo:
    def __init__(self):
        self.database = _Database()

    def __getitem__(self, name):
        return self.database

    def close(self):
        pass


class _FakeQdrant:
    def __init__(self):
        self.points = {}
        self.dropped = 0

    def __call__(self, method, path, **kwargs):
        if method == "GET" and path == "":
            return {"result": {"points_count": len(self.points)}}
        if method == "PUT" and path.startswith("/points"):
            for punto in kwargs["json"]["points"]:
                self.points[punto["id"]] = punto
            return {}
        if method == "POST" and path.startswith("/points/delete"):
            for point_id in kwargs["json"]["points"]:
                self.points.pop(point_id, None)
            return {}
        if method == "POST" and path.startswith("/points/search"):
            rows = [
                {"score": 0.9, "payload": value["payload"]}
                for value in list(self.points.values())[: kwargs["json"]["limit"]]
            ]
            return {"result": rows}
        if method == "POST" and path.startswith("/points/scroll"):
            rows = [
                {"id": key, "payload": value["payload"]}
                for key, value in list(self.points.items())[: kwargs["json"]["limit"]]
            ]
            return {"result": {"points": rows, "next_page_offset": None}}
        return {}


class DbAdminTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = FakePipeline()
        self.mongo = _FakeMongo()
        self.qdrant = _FakeQdrant()
        self.pipeline.mongo = self.mongo

        def _mongo(_self):
            return self.mongo, self.mongo.database

        def _qdrant(_self, method, path, **kw):
            return self.qdrant(method, path, **kw)

        def _drop(_self):
            self.qdrant.dropped += 1

        db_admin.DbAdmin._mongo = _mongo  # type: ignore[method-assign]
        db_admin.DbAdmin._qdrant = _qdrant  # type: ignore[method-assign]
        db_admin.DbAdmin._borrar_coleccion = _drop  # type: ignore[method-assign]
        db_admin.DbAdmin._crear_coleccion_vacia = lambda _self: None  # type: ignore[method-assign]
        self.admin = db_admin.DbAdmin(self.pipeline)
        self.client = TestClient(build_app(self.pipeline))

    def _crear(self, video_id="aaaaaaaaaaa", letra="el amor de verano"):
        return self.admin.crear_cancion(
            {
                "video_id": video_id,
                "title": "Amor de verano",
                "track": "Amor de verano",
                "artist": "Sol",
                "language": "es",
                "lyrics": letra,
                "backend": "manual",
            }
        )

    def test_validation_rejects_bad_ids_and_empty_lyrics(self):
        app = db_admin.DbAdmin(self.pipeline)
        with self.assertRaises(db_admin.DbError):
            app.crear_cancion({"video_id": "short", "title": "x", "lyrics": "y"})
        with self.assertRaises(db_admin.DbError):
            app.crear_cancion({"video_id": "aaaaaaaaaaa", "title": "x", "lyrics": "  "})

    def test_create_indexes_mongo_and_qdrant(self):
        cancion = self._crear()
        self.assertEqual(cancion["video_id"], "aaaaaaaaaaa")
        self.assertIn("aaaaaaaaaaa", self.mongo.database["songs"].docs)
        self.assertEqual(len(self.qdrant.points), 1)
        self.assertEqual(self.pipeline.indexer.id_de("aaaaaaaaaaa"), 0)
        self.assertEqual(
            self.pipeline.indexer.buscar("verano", 1)["results"][0]["video_id"],
            "aaaaaaaaaaa",
        )

    def test_create_duplicate_is_conflict(self):
        self._crear()
        with self.assertRaises(db_admin.DbError) as ctx:
            self._crear()
        self.assertEqual(ctx.exception.status, 409)

    def test_update_rewrites_terms_and_vector(self):
        self._crear()
        self.admin.actualizar_cancion(
            "aaaaaaaaaaa",
            {
                "video_id": "aaaaaaaaaaa",
                "title": "Invierno",
                "track": "Invierno",
                "artist": "Sur",
                "language": "es",
                "lyrics": "el invierno y la nieve",
                "backend": "manual",
            },
        )
        self.assertEqual(self.pipeline.indexer.titulos[0], "Invierno")
        self.assertEqual(
            self.pipeline.indexer.buscar("invierno", 1)["results"][0]["video_id"],
            "aaaaaaaaaaa",
        )
        self.assertNotIn("verano", self.pipeline.indexer.vocabulary)
        self.assertEqual(
            self.qdrant.points[core.id_punto("aaaaaaaaaaa")]["payload"]["title"],
            "Invierno",
        )

    def test_delete_removes_mongo_index_and_vector(self):
        self._crear()
        self.admin.eliminar_cancion("aaaaaaaaaaa")
        self.assertEqual(self.mongo.database["songs"].docs, {})
        self.assertEqual(self.pipeline.indexer.docs_id, set())
        self.assertEqual(self.qdrant.points, {})

    def test_embed_returns_the_indexing_model_vectors(self):
        payload = self.admin.embeber_textos(["winter love"])
        self.assertEqual(payload["model"], self.pipeline.indexer.modelo_id)
        self.assertEqual(payload["dim"], 8)
        self.assertEqual(len(payload["vectors"]), 1)
        self.assertEqual(len(payload["vectors"][0]), 8)

    def test_semantic_search_returns_qdrant_hits(self):
        self._crear()
        payload = self.admin.buscar_semantico("verano", limite=3)
        self.assertEqual(payload["engine"], "embeddings")
        self.assertEqual(payload["results"][0]["video_id"], "aaaaaaaaaaa")
        self.assertGreater(payload["results"][0]["score"], 0)

    def test_reset_drops_and_rebuilds_vectors(self):
        self._crear()
        resultado = self.admin.resetear_vectores()
        self.assertTrue(resultado["reset"])
        self.assertEqual(self.qdrant.dropped, 1)
        self.assertGreaterEqual(self.pipeline.publicaciones, 1)

    def test_api_routes(self):
        self.assertEqual(self.client.get("/db/health").status_code, 200)
        created = self.client.post(
            "/db/songs",
            json={
                "video_id": "bbbbbbbbbbb",
                "title": "Winter Love",
                "artist": "North",
                "language": "en",
                "lyrics": "winter love is cold",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(self.client.get("/db/overview").json()["mongo"]["songs"], 1)
        self.assertEqual(self.client.get("/db/songs").json()["total"], 1)
        updated = self.client.put(
            "/db/songs/bbbbbbbbbbb",
            json={
                "title": "Winter",
                "artist": "North",
                "language": "en",
                "lyrics": "winter is cold and the snow falls",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["track"], "Winter")
        self.assertEqual(self.client.get("/db/songs/bbbbbbbbbbb").status_code, 200)
        embed = self.client.post("/db/embed", json={"texts": ["winter"]})
        self.assertEqual(embed.status_code, 200, embed.text)
        self.assertEqual(embed.json()["dim"], 8)
        found = self.client.post("/db/search", json={"query": "winter", "limit": 3})
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()["results"][0]["video_id"], "bbbbbbbbbbb")
        self.assertEqual(self.client.delete("/db/songs/bbbbbbbbbbb").status_code, 200)
        self.assertEqual(self.client.get("/db/songs/bbbbbbbbbbb").status_code, 404)
        self.assertEqual(self.client.get("/db/songs/zzzzzzzzzzz").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
