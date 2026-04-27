import logging
from typing import Optional

from src.api.storygraph_client import StorygraphClient
from src.db.models import Book, State
from src.sync_clients.sync_client_interface import SyncClient, SyncResult, UpdateProgressRequest, ServiceState

logger = logging.getLogger(__name__)


class StorygraphSyncClient(SyncClient):
    """Follower-only StoryGraph sync client (either-or mode)."""

    def __init__(self, storygraph_client: StorygraphClient, ebook_parser):
        super().__init__(ebook_parser)
        self.storygraph_client = storygraph_client

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
            self.storygraph_client.update_progress(book=book, locator_result=request.locator_result)
            return SyncResult(request.locator_result.percentage, True)
        except Exception as e:
            logger.warning("StoryGraph update skipped: %s", e)
            return SyncResult(None, False)
