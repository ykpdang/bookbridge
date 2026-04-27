import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class StorygraphClient:
    """Minimal StoryGraph client using session cookies (unofficial API surface)."""

    def __init__(self):
        self.base_url = os.environ.get("STORYGRAPH_BASE_URL", "https://app.thestorygraph.com").rstrip("/")
        self.session_cookie = (os.environ.get("STORYGRAPH_SESSION_COOKIE") or "").strip()
        self.remember_user_token = (os.environ.get("STORYGRAPH_REMEMBER_USER_TOKEN") or "").strip()
        self.timeout = 10

    def _provider_enabled(self) -> bool:
        provider = (os.environ.get("PROGRESS_TRACKER_PROVIDER") or "").strip().lower()
        if provider:
            return provider == "storygraph"

        # Backward-compat fallback if provider is not set
        return (os.environ.get("STORYGRAPH_ENABLED", "false").strip().lower() == "true")

    def is_configured(self) -> bool:
        if not self._provider_enabled():
            return False
        return bool(self.session_cookie and self.remember_user_token)

    def _cookie_header(self) -> str:
        return (
            f"_story_graph_session={self.session_cookie}; "
            f"remember_user_token={self.remember_user_token}"
        )

    def check_connection(self) -> bool:
        """
        Validate StoryGraph cookie auth by loading the currently-reading page.
        This is intentionally lightweight due unofficial API instability.
        """
        if not self._provider_enabled():
            raise Exception("StoryGraph is disabled")

        if not self.session_cookie or not self.remember_user_token:
            raise Exception("Missing StoryGraph session cookies")

        resp = requests.get(
            f"{self.base_url}/currently-reading",
            headers={
                "Cookie": self._cookie_header(),
                "User-Agent": "ABS-KoSync-Bridge/StoryGraph",
            },
            timeout=self.timeout,
            allow_redirects=False,
        )

        if resp.status_code in (200, 302):
            logger.info("✅ StoryGraph connection verified")
            return True

        if resp.status_code in (401, 403):
            raise Exception("StoryGraph authentication failed")

        raise Exception(f"StoryGraph returned HTTP {resp.status_code}")

    def update_progress(self, *_args, **_kwargs) -> bool:
        """
        Placeholder to keep either-or plumbing stable.
        Full progress update workflow will be implemented separately.
        """
        logger.info("StoryGraph update requested (placeholder implementation)")
        return False
