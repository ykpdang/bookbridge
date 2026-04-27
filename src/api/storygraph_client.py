import logging
import os
import re
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.utils.string_utils import calculate_similarity, clean_book_title

logger = logging.getLogger(__name__)


class StorygraphClient:
    """StoryGraph client using unofficial web endpoints + session cookies."""

    def __init__(self):
        self.base_url = os.environ.get("STORYGRAPH_BASE_URL", "https://app.thestorygraph.com").rstrip("/")
        self.session_cookie = (os.environ.get("STORYGRAPH_SESSION_COOKIE") or "").strip()
        self.remember_user_token = (os.environ.get("STORYGRAPH_REMEMBER_USER_TOKEN") or "").strip()
        self.timeout = 12
        self.user_id = "storygraph_user"

    def _provider_enabled(self) -> bool:
        provider = (os.environ.get("PROGRESS_TRACKER_PROVIDER") or "").strip().lower()
        if provider:
            return provider == "storygraph"
        return (os.environ.get("STORYGRAPH_ENABLED", "false").strip().lower() == "true")

    def is_configured(self) -> bool:
        if not self._provider_enabled():
            return False
        enabled_val = (os.environ.get("STORYGRAPH_ENABLED", "").strip().lower())
        if enabled_val == "false":
            return False
        return bool(self.session_cookie and self.remember_user_token)

    def _cookie_header(self) -> str:
        return (
            f"remember_user_token={self.remember_user_token}; "
            "cookies_popup_seen=yes; plus_popup_seen=yes; "
            f"_story_graph_session={self.session_cookie}"
        )

    def _headers(self, *, accept: str = "text/html,application/xhtml+xml") -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Cookie": self._cookie_header(),
            "Accept": accept,
            "Origin": self.base_url,
            "Referer": self.base_url,
            "DNT": "1",
        }

    @staticmethod
    def _extract_csrf(html: str) -> Optional[str]:
        if not html:
            return None
        patterns = [
            r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
            r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']csrf-token["\']',
            r'name=["\']authenticity_token["\']\s+value=["\']([^"\']+)["\']',
            r'value=["\']([^"\']+)["\']\s+name=["\']authenticity_token["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _parse_status_id(status_text: str) -> Optional[int]:
        txt = (status_text or "").strip().lower()
        if "currently reading" in txt or "rereading" in txt:
            return 2
        if txt in {"to-read", "to read"}:
            return 1
        if "did not finish" in txt:
            return 5
        if "paused" in txt:
            return 4
        if txt == "read" or txt.endswith(" read"):
            return 3
        return None

    def _request(self, path: str, *, method: str = "GET", data: dict | None = None, headers: dict | None = None):
        if not self.is_configured():
            return None

        url = path if path.startswith("http") else f"{self.base_url}{path}"
        req_headers = self._headers()
        if headers:
            req_headers.update(headers)

        try:
            if method.upper() == "POST":
                return requests.post(url, data=data or {}, headers=req_headers, timeout=self.timeout)
            return requests.get(url, headers=req_headers, timeout=self.timeout)
        except Exception as exc:
            logger.warning("StoryGraph request failed for %s: %s", url, exc)
            return None

    def check_connection(self) -> bool:
        if not self.is_configured():
            raise Exception("StoryGraph is disabled or missing cookies")

        resp = self._request("/currently-reading", headers={"Accept": "text/html"})
        if not resp:
            raise Exception("StoryGraph request failed")

        if resp.status_code in (200, 302):
            logger.info("✅ StoryGraph connection verified")
            return True
        if resp.status_code in (401, 403):
            raise Exception("StoryGraph authentication failed")

        raise Exception(f"StoryGraph returned HTTP {resp.status_code}")

    def search_books(self, title: str, author: str = "") -> list[dict]:
        query = f"{title} {author}".strip()
        if not query:
            return []

        resp = self._request(f"/browse?search_term={requests.utils.quote(query)}")
        if not resp or resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        seen_ids = set()

        for card in soup.select(".book-title-author-and-series"):
            title_link = card.select_one("a[href^='/books/']")
            if not title_link:
                continue
            href = title_link.get("href", "")
            match = re.search(r"/books/([^/?#]+)", href)
            if not match:
                continue
            book_id = match.group(1)
            if book_id in seen_ids:
                continue
            seen_ids.add(book_id)

            author_link = card.select_one("a[href^='/authors/']")
            results.append(
                {
                    "book_id": book_id,
                    "title": title_link.get_text(" ", strip=True),
                    "author": author_link.get_text(" ", strip=True) if author_link else "",
                }
            )

        return results

    def resolve_book(self, title: str, author: str = "", isbn: str = "") -> Optional[dict]:
        candidates = []
        if isbn:
            candidates.extend(self.search_books(isbn, ""))
        candidates.extend(self.search_books(title, author))

        if not candidates:
            return None

        clean_title = clean_book_title(title or "")
        best = None
        best_score = -1
        for item in candidates:
            score = calculate_similarity(clean_title, clean_book_title(item.get("title", "")))
            if author and item.get("author"):
                score = (score + calculate_similarity(author.lower(), item.get("author", "").lower())) / 2
            if score > best_score:
                best_score = score
                best = item

        return best

    def get_user_book(self, book_id: str) -> Optional[dict]:
        if not book_id:
            return None

        resp = self._request(f"/books/{book_id}")
        if not resp or resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        status_text = ""
        status_label = soup.select_one(".read-status-label")
        if status_label:
            status_text = status_label.get_text(" ", strip=True)

        progress_type = "percentage"
        progress_type_el = soup.select_one(".read-status-progress-type option[selected='selected']")
        if progress_type_el and progress_type_el.get("value"):
            progress_type = progress_type_el["value"]

        def int_value(selector: str) -> int:
            node = soup.select_one(selector)
            if not node:
                return 0
            val = node.get("value") or "0"
            try:
                return int(float(val))
            except Exception:
                return 0

        progress_pages = int_value(".read-status-last-reached-pages")
        total_pages = int_value(".read-status-book-num-of-pages")
        percentage = int_value(".read-status-last-reached-percent")

        if percentage == 0:
            bar = re.search(r"width:\s*(\d+)%", resp.text)
            if bar:
                percentage = int(bar.group(1))

        return {
            "id": book_id,
            "book_id": book_id,
            "status_id": self._parse_status_id(status_text),
            "last_reached_percent": percentage,
            "progress_type": progress_type,
            "book_num_of_pages": total_pages,
            "user_book_reads": [
                {
                    "id": f"{book_id}_read",
                    "edition_id": book_id,
                    "progress_pages": progress_pages,
                    "started_at": date.today().isoformat(),
                }
            ],
        }

    def update_status(self, book_id: str, status_id: int) -> bool:
        status_map = {
            1: "to-read",
            2: "currently-reading",
            3: "read",
            4: "paused",
            5: "did-not-finish",
        }
        status = status_map.get(int(status_id or 0))
        if not book_id or not status:
            return False

        # StoryGraph endpoint used by the KOReader plugin fork.
        resp = self._request(f"/update-status.js?book_id={book_id}&status={status}", method="POST")
        return bool(resp and resp.status_code in (200, 204, 302))

    def update_progress(self, book_id: str, percentage: float, started_at: Optional[str] = None) -> bool:
        if not book_id:
            return False

        # Load book page first to obtain CSRF/authenticity token and current form values.
        page = self._request(f"/books/{book_id}")
        if not page or page.status_code != 200:
            return False

        csrf = self._extract_csrf(page.text)
        if not csrf:
            logger.warning("StoryGraph: could not extract CSRF token")
            return False

        clamped_percent = max(0, min(100, int(round((percentage or 0) * 100 if percentage <= 1 else percentage))))

        payload = {
            "book_id": book_id,
            "last_reached_percent": str(clamped_percent),
            "progress_type": "percentage",
            "started_at": started_at or date.today().isoformat(),
            "authenticity_token": csrf,
        }

        resp = self._request(
            f"/update-progress.js?book_id={book_id}",
            method="POST",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/javascript, application/javascript, */*; q=0.01",
                "X-CSRF-Token": csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.base_url}/books/{book_id}",
            },
        )

        ok = bool(resp and resp.status_code in (200, 204, 302))
        if not ok and resp is not None:
            logger.warning("StoryGraph progress update failed: HTTP %s", resp.status_code)
        return ok
