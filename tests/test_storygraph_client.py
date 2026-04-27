import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.storygraph_client import StorygraphClient


class TestStorygraphClient(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "PROGRESS_TRACKER_PROVIDER": "storygraph",
                "STORYGRAPH_ENABLED": "true",
                "STORYGRAPH_SESSION_COOKIE": "session",
                "STORYGRAPH_REMEMBER_USER_TOKEN": "remember",
            },
            clear=False,
        )
        self.env_patcher.start()
        self.client = StorygraphClient()

    def tearDown(self):
        self.env_patcher.stop()

    @patch("src.api.storygraph_client.requests.get")
    def test_check_connection_ok(self, mock_get):
        mock_get.return_value = Mock(status_code=200)
        self.assertTrue(self.client.check_connection())

    @patch("src.api.storygraph_client.requests.get")
    def test_search_books_parses_results(self, mock_get):
        html = """
        <div class='book-title-author-and-series'>
          <a href='/books/abc-123'>Book Title</a>
          <a href='/authors/x'>Author Name</a>
        </div>
        """
        mock_get.return_value = Mock(status_code=200, text=html)

        results = self.client.search_books("Book", "Author")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["book_id"], "abc-123")

    @patch("src.api.storygraph_client.requests.get")
    @patch("src.api.storygraph_client.requests.post")
    def test_update_progress_posts_to_endpoint(self, mock_post, mock_get):
        html = '<meta name="csrf-token" content="csrf123" />'
        mock_get.return_value = Mock(status_code=200, text=html)
        mock_post.return_value = Mock(status_code=200)

        ok = self.client.update_progress("book-1", 0.42)
        self.assertTrue(ok)
        self.assertIn("/update-progress.js?book_id=book-1", mock_post.call_args[0][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
