"""Isolated regressions for auto-queue row eligibility filtering."""
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from backend.routers.extension import get_auto_queue, AutoQueueRow


class AutoQueueTests(unittest.TestCase):
    @patch("backend.routers.extension._require_api_key")
    @patch("backend.services.sheets.get_all_rows")
    @patch("backend.database.SessionLocal")
    def test_draft_scheduled_rows_without_upload_id_are_eligible(
        self, mock_session_local, mock_get_all_rows, mock_require_auth
    ):
        """Even rows in sheets often have draft scheduled dates pre-filled.
        They MUST be eligible if they have no upload_id and no DB post."""
        # Setup mock DB session with no existing posts
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_session_local.return_value.__enter__.return_value = mock_db

        mock_get_all_rows.return_value = [
            # Row 1: already uploaded
            {
                "id": "1",
                "prompt": "Taj Mahal prompt",
                "title": "Taj Mahal",
                "scheduled": "2026-10-05T12:30:00+05:30",
                "upload id": "YT_VIDEO_1",
            },
            # Row 2: draft scheduled date, but NO upload id! (The landmark that was previously skipped)
            {
                "id": "2",
                "prompt": "Eiffel Tower prompt",
                "title": "Eiffel Tower",
                "scheduled": "2026-10-05T18:30:00+05:30",
                "upload id": "",
            },
            # Row 3: no schedule, no upload id
            {
                "id": "3",
                "prompt": "Burj Khalifa prompt",
                "title": "Burj Khalifa",
                "scheduled": "",
                "upload id": "",
            },
        ]

        resp = get_auto_queue(channel="sky_keepers", limit=10)
        self.assertEqual(resp.total, 2)
        row_ids = [r.id for r in resp.rows]
        self.assertIn("2", row_ids, "Row 2 with draft schedule must be in auto-queue")
        self.assertIn("3", row_ids, "Row 3 must be in auto-queue")
        self.assertNotIn("1", row_ids, "Row 1 with upload id must NOT be in auto-queue")

    @patch("backend.routers.extension._require_api_key")
    @patch("backend.services.sheets.get_all_rows")
    @patch("backend.database.SessionLocal")
    def test_rows_with_existing_db_posts_are_skipped(
        self, mock_session_local, mock_get_all_rows, mock_require_auth
    ):
        """Rows that already have an active post in the database must not be duplicated."""
        # Row 2 already exists in the database
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [("2",)]
        mock_session_local.return_value.__enter__.return_value = mock_db

        mock_get_all_rows.return_value = [
            {
                "id": "2",
                "prompt": "Eiffel Tower prompt",
                "title": "Eiffel Tower",
                "scheduled": "2026-10-05T18:30:00+05:30",
                "upload id": "",
            },
            {
                "id": "4",
                "prompt": "Great Wall prompt",
                "title": "Great Wall",
                "scheduled": "2026-10-06T12:30:00+05:30",
                "upload id": "",
            },
        ]

        resp = get_auto_queue(channel="sky_keepers", limit=10)
        self.assertEqual(resp.total, 1)
        self.assertEqual(resp.rows[0].id, "4")


if __name__ == "__main__":
    unittest.main()
