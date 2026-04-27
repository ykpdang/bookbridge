import unittest
from unittest.mock import Mock

from src.sync_clients.storygraph_sync_client import StorygraphSyncClient
from src.sync_clients.sync_client_interface import UpdateProgressRequest, LocatorResult


class _Book:
    def __init__(self, abs_id="a1", abs_title="Title"):
        self.abs_id = abs_id
        self.abs_title = abs_title


class TestStorygraphSyncClient(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.is_configured.return_value = True
        self.client.resolve_book.return_value = {"book_id": "sg-1"}
        self.client.update_status.return_value = True
        self.client.update_progress.return_value = True

        self.abs_client = Mock()
        self.abs_client.get_item_details.return_value = {
            "media": {"metadata": {"title": "Title", "authorName": "Author", "isbn": "123"}}
        }

        self.sync = StorygraphSyncClient(self.client, ebook_parser=Mock(), abs_client=self.abs_client)

    def test_update_progress_resolves_and_updates(self):
        book = _Book()
        req = UpdateProgressRequest(locator_result=LocatorResult(percentage=0.5))

        result = self.sync.update_progress(book, req)

        self.assertTrue(result.success)
        self.client.resolve_book.assert_called_once()
        self.client.update_status.assert_called_once()
        self.client.update_progress.assert_called_once_with("sg-1", 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
