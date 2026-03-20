import unittest
from unittest.mock import MagicMock, patch
from src.sync_clients.abs_ebook_sync_client import ABSEbookSyncClient
from src.db.models import Book
from src.sync_clients.sync_client_interface import UpdateProgressRequest, LocatorResult

class TestABSEbookSyncClient(unittest.TestCase):

    def setUp(self):
        self.mock_abs_client = MagicMock()
        self.mock_ebook_parser = MagicMock()
        self.client = ABSEbookSyncClient(self.mock_abs_client, self.mock_ebook_parser)
        self.book = Book(abs_id="test-book-id", ebook_filename="test.epub")

    def test_get_service_state_success(self):
        self.mock_abs_client.get_progress.return_value = {
            'ebookProgress': 0.5,
            'ebookLocation': 'epubcfi(/6/14!/4/2/1:0)'
        }
        state = self.client.get_service_state(self.book, None)
        self.assertIsNotNone(state)
        self.assertEqual(state.current['pct'], 0.5)

    def test_update_progress_success(self):
        locator = LocatorResult(percentage=0.75, cfi="epubcfi(/6/20!/4:0)")
        request = UpdateProgressRequest(locator_result=locator)
        self.mock_abs_client.update_ebook_progress.return_value = True
        with patch("src.services.write_tracker.record_write") as mock_record_write:
            self.client.update_progress(self.book, request)
        self.mock_abs_client.update_ebook_progress.assert_called_with(
            "test-book-id", 0.75, "epubcfi(/6/20!/4:0)"
        )
        mock_record_write.assert_called_once_with("ABS_Ebook", "test-book-id")

    def test_threshold_is_percent_scaled(self):
        self.assertEqual(self.client.delta_abs_thresh, 0.01)

    def test_update_progress_does_not_record_write_on_failure(self):
        locator = LocatorResult(percentage=0.75, cfi="epubcfi(/6/20!/4:0)")
        request = UpdateProgressRequest(locator_result=locator)
        self.mock_abs_client.update_ebook_progress.return_value = False

        with patch("src.services.write_tracker.record_write") as mock_record_write:
            self.client.update_progress(self.book, request)

        mock_record_write.assert_not_called()

if __name__ == '__main__':
    unittest.main()
