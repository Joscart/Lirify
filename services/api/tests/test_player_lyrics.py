import unittest
from unittest.mock import Mock, patch

import requests

from test_course_search import main, song
import player_api


class PlayerLyricsTests(unittest.TestCase):
    def setUp(self):
        player_api._SYNC_CACHE.clear()
        player_api._LYRIC_CACHE.clear()

    def test_stored_timestamps_need_no_external_request(self):
        track = song(100, "[00:01.20]Hola mundo\n[00:03.50]Otra línea")
        with patch.object(player_api.requests, "get") as get:
            result = player_api.playback_lyrics(track)
        get.assert_not_called()
        self.assertTrue(result["synced"])
        self.assertEqual([line["t"] for line in result["lines"]], [1.2, 3.5])

    def test_playback_enriches_plain_lyrics_without_changing_index(self):
        track = song(101, "Hola mundo\nOtra línea")
        response = Mock()
        response.json.return_value = [{
            "trackName": track["track"], "artistName": track["artist"],
            "duration": 120, "syncedLyrics": "[00:01.20]Hola mundo\n[00:03.50]Otra línea",
        }]
        with patch.object(player_api.requests, "get", return_value=response) as get:
            result = player_api.playback_lyrics(track)
            self.assertEqual(player_api.playback_lyrics(track), result)
        get.assert_called_once()
        self.assertEqual(result["source"], "lrclib")
        self.assertTrue(result["synced"])
        self.assertFalse(player_api.lyrics_for(track)["synced"])
        self.assertEqual(track["lyrics"], "Hola mundo\nOtra línea")

    def test_provider_failure_keeps_plain_lyrics_untimed(self):
        track = song(102, "Hola mundo\nOtra línea")
        with patch.object(player_api.requests, "get", side_effect=requests.Timeout):
            result = player_api.playback_lyrics(track)
        self.assertFalse(result["synced"])
        self.assertEqual([line["t"] for line in result["lines"]], [None, None])

    def test_different_recording_is_not_used(self):
        track = song(103, "Hola mundo\nOtra línea")
        response = Mock()
        response.json.return_value = [{
            "trackName": track["track"], "artistName": track["artist"],
            "duration": 300, "syncedLyrics": "[00:01.20]Hola mundo\n[00:03.50]Otra línea",
        }]
        with patch.dict(player_api.DURATIONS, {track["video_id"]: 120}), patch.object(player_api.requests, "get", return_value=response):
            result = player_api.playback_lyrics(track)
        self.assertFalse(result["synced"])

    def test_enhanced_lrc_preserves_real_word_times(self):
        result = player_api.parse_lyrics("[00:02.00]<00:02.00>Hola <00:02.50>mundo")
        self.assertEqual(result["lines"][0]["words"], [
            {"t": 2.0, "text": "Hola"}, {"t": 2.5, "text": "mundo"},
        ])
