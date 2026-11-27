import unittest
from unittest.mock import patch

import numpy as np

with patch.dict("os.environ", {
    "MONGODB_URI": "", "MONGO_URI": "", "QDRANT_URL": "",
    "PUBLIC_RATE_LIMIT_PER_MINUTE": "0",
}):
    import main


def song(number, lyrics, language="es", title=None):
    return {
        "video_id": f"video{number:06d}",
        "track": title or f"Canción {number}",
        "artist": "Artista de prueba",
        "lyrics": lyrics,
        "language": language,
        "backend": "fixture",
    }


def catalogue(songs):
    index, vocab, df, tfidf, _, _, _, _, matrices, _ = main.build_index(songs)
    return {
        "songs": songs, "index": index, "vocab": vocab,
        "doc_freq": df, "tfidf": tfidf, "matrices": matrices,
    }


class CourseSearchTests(unittest.TestCase):
    def search(self, state, query):
        with patch.object(main, "STATE", state):
            return main.course_search(query)

    def test_route_uses_course_search(self):
        route = next(route for route in main.app.routes if route.path == "/api/player/course-search")
        self.assertIs(route.endpoint, main.course_search)
        self.assertEqual(route.methods, {"GET"})

    def test_unicode_preserves_enye_and_breaks_punctuation(self):
        self.assertEqual(main.remove_special("CORAZÓN,\nmañana"), "corazon mañana")
        self.assertNotEqual(main.remove_special("ano"), main.remove_special("año"))

    def test_positional_index_log_weights_and_cosine_matrix(self):
        state = catalogue([
            song(1, "moon moon river", "en"),
            song(2, "river blue", "en"),
            song(3, "blue", "en"),
        ])
        self.assertEqual(state["index"]["moon"]["0"], [1, 2])
        row = state["vocab"].index("moon")
        numerator = (1 + np.log10(2)) * np.log10(3)
        other_weight = np.log10(3 / 2)
        self.assertAlmostEqual(
            state["tfidf"][row, 0], numerator / np.hypot(numerator, other_weight), places=6
        )
        np.testing.assert_allclose(np.linalg.norm(state["tfidf"], axis=0), 1, atol=1e-6)
        np.testing.assert_allclose(
            state["matrices"]["lyrics"], state["tfidf"].T @ state["tfidf"], atol=1e-6
        )

    def test_every_top_result_excludes_the_entire_top_ten(self):
        state = catalogue([
            *(song(i, f"[00:02.50]Mi amor es eterno, luces {i}.") for i in range(10)),
            *(song(i, f"La noche tiene un eco eterno {i}.") for i in range(10, 14)),
        ])
        payload = self.search(state, "amor")
        results = payload["results"]
        top_ids = {row["id"] for row in results}
        self.assertEqual(payload["scanned"], 14)
        self.assertEqual(len(top_ids), 10)
        self.assertEqual([row["score"] for row in results], sorted(
            [row["score"] for row in results], reverse=True
        ))
        for row in results:
            self.assertGreater(row["score"], 0)
            self.assertLessEqual(row["score"], 1)
            self.assertTrue(row["snippet"].startswith("Mi amor"))
            recommendations = row["recommendations"]
            ids = {item["id"] for item in recommendations}
            self.assertEqual(len(ids), 3)
            self.assertTrue(top_ids.isdisjoint(ids))
            self.assertEqual([item["score"] for item in recommendations], sorted(
                [item["score"] for item in recommendations], reverse=True
            ))

    def test_spanish_uses_the_same_stemmer_as_the_document(self):
        state = catalogue([
            song(1, "La noche tiene estrellas\n[00:10.00]Besando bajo el cielo."),
            song(2, "corazón y mañana"),
            song(3, "You make the sky blue", "en"),
            song(4, "Mountains in the snow", "en", title="Besando"),
        ])
        results = self.search(state, "besando")["results"]
        self.assertEqual([row["id"] for row in results], ["video000001"])
        self.assertEqual(results[0]["snippet"], "Besando bajo el cielo.")
        self.assertEqual(self.search(state, "corazon")["results"][0]["id"], "video000002")
        self.assertEqual(self.search(state, "snow")["results"][0]["id"], "video000004")

    def test_empty_and_unknown_queries(self):
        state = catalogue([song(1, "corazón mañana"), song(2, "sol y luna")])
        for query in ("", "   ", "asdfgh", "de la"):
            with self.subTest(query=query):
                self.assertEqual(self.search(state, query)["results"], [])
        self.assertEqual(self.search({"songs": []}, "amor")["scanned"], 0)

    def test_small_catalogue_returns_only_available_candidates(self):
        state = catalogue([song(1, "sol y mar"), song(2, "sol y montaña"), song(3, "cielo azul")])
        results = self.search(state, "sol")["results"]
        self.assertEqual(len(results), 2)
        for row in results:
            self.assertEqual([item["id"] for item in row["recommendations"]], ["video000003"])
