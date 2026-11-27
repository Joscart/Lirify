import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("legacy_migration", ROOT / "scripts/migrate_json_to_mongo.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class CatalogueSeedTests(unittest.TestCase):
    def test_seed_is_insert_only(self):
        song = {"video_id": "video000001", "title": "Song", "lyrics": "A verse"}
        update = migration.song_update(song, 42, True)
        self.assertEqual(set(update), {"$setOnInsert"})
        self.assertEqual(update["$setOnInsert"]["videoId"], song["video_id"])
        self.assertEqual(update["$setOnInsert"]["lyrics"], song["lyrics"])
        self.assertEqual(update["$setOnInsert"]["createdAt"], 42)

    def test_bundled_catalogue_can_be_seeded(self):
        songs = json.loads((ROOT / "data/songs.json").read_text(encoding="utf-8"))
        updates = [migration.song_update(song, 42, True) for song in songs]
        self.assertTrue(all(updates))
        self.assertEqual(len({doc["$setOnInsert"]["videoId"] for doc in updates}), len(songs))

    def test_empty_lyrics_and_invalid_id_are_excluded(self):
        self.assertIsNone(migration.song_update({"video_id": "bad", "lyrics": "text"}, 42, True))
        self.assertIsNone(migration.song_update({"video_id": "video000001", "lyrics": " "}, 42, True))
