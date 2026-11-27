import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from test_course_search import main


class PlayerImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_uses_validated_playlist_and_existing_queue(self):
        url = "https://music.youtube.com/playlist?list=PLfixture123456789"
        with patch.object(main, "enqueue_playlist", AsyncMock(return_value="job-test")) as enqueue:
            result = await main.player_import(main.UrlIn(url=url))
        self.assertEqual(result, {"job_id": "job-test"})
        enqueue.assert_awaited_once()
        self.assertEqual(enqueue.await_args.args[-1], "astro-webui")

    async def test_invalid_playlist_is_not_queued(self):
        with patch.object(main, "enqueue_playlist", AsyncMock()) as enqueue:
            with self.assertRaises(HTTPException):
                await main.player_import(main.UrlIn(url="https://example.com/playlist?list=PLfixture123456789"))
        enqueue.assert_not_called()

    def test_status_returns_only_job_progress(self):
        with patch.object(main, "job_snapshot", return_value={"status": "committed", "stage": "commit", "added": 3, "url": "private metadata"}):
            result = main.player_import_status("job-test")
        self.assertEqual(result, {"status": "committed", "stage": "commit", "added": 3, "error": None})
