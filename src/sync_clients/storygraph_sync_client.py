import logging
from typing import Optional

from src.api.storygraph_client import StorygraphClient
from src.db.models import Book, State
from src.sync_clients.sync_client_interface import SyncClient, SyncResult, UpdateProgressRequest, ServiceState

logger = logging.getLogger(__name__)


class StorygraphSyncClient(SyncClient):
    """Follower-only StoryGraph sync client (either-or mode)."""

    def __init__(self, storygraph_client: StorygraphClient, ebook_parser, abs_client=None):
        super().__init__(ebook_parser)
        self.storygraph_client = storygraph_client
        self.abs_client = abs_client
        self._book_id_cache: dict[str, str] = {}

    def is_configured(self) -> bool:
        return self.storygraph_client.is_configured()

    def check_connection(self):
        return self.storygraph_client.check_connection()

    def can_be_leader(self) -> bool:
        return False

    def get_service_state(
        self,
        book: Book,
        prev_state: Optional[State],
        title_snip: str = "",
        bulk_context: dict = None,
    ) -> Optional[ServiceState]:
        return None

    def get_text_from_current_state(self, book: Book, state: ServiceState) -> Optional[str]:
        return None

    def update_progress(self, book: Book, request: UpdateProgressRequest) -> SyncResult:
        if not self.is_configured():
            return SyncResult(None, False)

        try:
            book_id = self._resolve_book_id(book)
            if not book_id:
                return SyncResult(None, False)

            percentage = float(request.locator_result.percentage or 0.0)
            if percentage > 0.99:
                self.storygraph_client.update_status(book_id, 3)
            elif percentage > 0.02:
                self.storygraph_client.update_status(book_id, 2)
            else:
                self.storygraph_client.update_status(book_id, 1)

            updated = self.storygraph_client.update_progress(book_id, percentage)
            return SyncResult(percentage if updated else None, bool(updated))
        except Exception as e:
            logger.warning("StoryGraph update skipped: %s", e)
            return SyncResult(None, False)

    def _resolve_book_id(self, book: Book) -> Optional[str]:
        cached = self._book_id_cache.get(book.abs_id)
        if cached:
            return cached

        if not self.abs_client:
            return None

        item = self.abs_client.get_item_details(book.abs_id)
        if not item:
            return None

        meta = item.get("media", {}).get("metadata", {})
        title = meta.get("title") or book.abs_title or ""
        author = meta.get("authorName") or ""
        isbn = meta.get("isbn") or meta.get("asin") or ""

        match = self.storygraph_client.resolve_book(title=title, author=author, isbn=isbn)
        if not match:
            return None

        book_id = match.get("book_id")
        if book_id:
            self._book_id_cache[book.abs_id] = book_id
        return book_id
