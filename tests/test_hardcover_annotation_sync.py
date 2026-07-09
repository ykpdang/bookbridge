"""
Tests for the Hardcover annotation spoke (private_notes approach).

Hardcover has no per-highlight API — annotations are written as a formatted
text block to user_books.private_notes via update_private_notes().
"""

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATA_DIR", "/tmp/hc_ann_test")

DOC_MD5 = "c" * 32


# ---------------------------------------------------------------------------
# HardcoverClient.update_private_notes tests
# ---------------------------------------------------------------------------

class TestHardcoverClientPrivateNotes(unittest.TestCase):
    def _client(self):
        from src.api.hardcover_client import HardcoverClient
        return HardcoverClient(credentials={"HARDCOVER_TOKEN": "tok", "HARDCOVER_ENABLED": "true"})

    def test_update_private_notes_success(self):
        c = self._client()
        c.query = MagicMock(return_value={"update_user_books_by_pk": {"id": 7}})
        self.assertTrue(c.update_private_notes(7, "some notes"))

    def test_update_private_notes_failure_returns_false(self):
        c = self._client()
        c.query = MagicMock(return_value=None)
        self.assertFalse(c.update_private_notes(7, "some notes"))

    def test_update_private_notes_empty_result_false(self):
        c = self._client()
        c.query = MagicMock(return_value={"update_user_books_by_pk": None})
        self.assertFalse(c.update_private_notes(7, ""))

    def test_get_user_book_id_found(self):
        c = self._client()
        c.get_user_id = MagicMock(return_value=99)
        c.query = MagicMock(return_value={"user_books": [{"id": 55}]})
        self.assertEqual(c.get_user_book_id(10), 55)

    def test_get_user_book_id_not_found(self):
        c = self._client()
        c.get_user_id = MagicMock(return_value=99)
        c.query = MagicMock(return_value={"user_books": []})
        self.assertIsNone(c.get_user_book_id(10))

    def test_get_user_book_id_no_user_id(self):
        c = self._client()
        c.get_user_id = MagicMock(return_value=None)
        self.assertIsNone(c.get_user_book_id(10))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    db = MagicMock()
    db.get_books_by_status.return_value = []
    db.get_linked_abs_ids.return_value = None
    return db


def _make_book(abs_id="abs-1", doc_md5=DOC_MD5):
    b = SimpleNamespace()
    b.abs_id = abs_id
    b.kosync_doc_id = doc_md5
    return b


_EPOCH = datetime(2026, 1, 1)
_NOW = datetime(2026, 7, 1, 12, 0, 0)


def _make_ann(
    id=1,
    drawer="lighten",
    color="yellow",
    text="highlighted text",
    note=None,
    pageno=5,
    deleted=False,
    hardcover_synced_at=None,
    updated_at=None,
):
    a = MagicMock()
    a.id = id
    a.drawer = drawer
    a.color = color
    a.text = text
    a.note = note
    a.pageno = pageno
    a.deleted = deleted
    a.hardcover_synced_at = hardcover_synced_at
    a.updated_at = updated_at if updated_at is not None else _NOW
    return a


def _make_session_with_rows(db, rows):
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    (
        session.query.return_value
        .filter.return_value
        .order_by.return_value
        .limit.return_value
        .all.return_value
    ) = rows
    db.get_session.return_value = session
    return session


# ---------------------------------------------------------------------------
# Color mapping tests
# ---------------------------------------------------------------------------

class TestHardcoverAnnotationSyncColorMapping(unittest.TestCase):
    def setUp(self):
        from src.services.hardcover_annotation_sync import HardcoverAnnotationSync
        self.sync = HardcoverAnnotationSync.__new__(HardcoverAnnotationSync)

    def test_yellow_maps(self):
        self.assertEqual(self.sync._ko_color_label("yellow"), "yellow")

    def test_purple_maps(self):
        self.assertEqual(self.sync._ko_color_label("purple"), "purple")

    def test_unknown_returns_empty(self):
        self.assertEqual(self.sync._ko_color_label("chartreuse"), "")

    def test_none_returns_empty(self):
        self.assertEqual(self.sync._ko_color_label(None), "")

    def test_case_insensitive(self):
        self.assertEqual(self.sync._ko_color_label("YELLOW"), "yellow")


# ---------------------------------------------------------------------------
# Format block tests
# ---------------------------------------------------------------------------

class TestHardcoverAnnotationSyncFormat(unittest.TestCase):
    def setUp(self):
        from src.services.hardcover_annotation_sync import HardcoverAnnotationSync
        self.sync = HardcoverAnnotationSync.__new__(HardcoverAnnotationSync)

    def test_format_annotation_includes_text(self):
        row = _make_ann(text="great passage", note=None, pageno=10, color="yellow")
        block = self.sync._format_annotation(row)
        self.assertIn("great passage", block)

    def test_format_annotation_includes_page_and_color(self):
        row = _make_ann(text="hello", pageno=42, color="red")
        block = self.sync._format_annotation(row)
        self.assertIn("p.42", block)
        self.assertIn("red", block)

    def test_format_annotation_includes_note(self):
        row = _make_ann(text="quote", note="my note")
        block = self.sync._format_annotation(row)
        self.assertIn("my note", block)

    def test_format_annotation_no_pageno(self):
        row = _make_ann(text="quote", pageno=None, color=None)
        block = self.sync._format_annotation(row)
        self.assertIn("quote", block)

    def test_build_notes_block_separates_with_divider(self):
        rows = [_make_ann(id=i, text=f"text {i}") for i in range(3)]
        block = self.sync._build_notes_block(rows)
        self.assertEqual(block.count("---"), 2)


# ---------------------------------------------------------------------------
# Sync logic tests
# ---------------------------------------------------------------------------

class TestHardcoverAnnotationSyncLogic(unittest.TestCase):
    def _make_sync(self, db=None):
        from src.services.hardcover_annotation_sync import HardcoverAnnotationSync
        return HardcoverAnnotationSync(db or _make_db())

    def _details(self, book_id=10):
        return SimpleNamespace(hardcover_book_id=book_id)

    def test_push_calls_update_private_notes(self):
        db = _make_db()
        row = _make_ann(id=1, hardcover_synced_at=None)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_id.return_value = 55
        client.update_private_notes.return_value = True

        result = sync._sync_book(1, client, _make_book())
        self.assertTrue(result)
        client.update_private_notes.assert_called_once()
        args = client.update_private_notes.call_args
        self.assertEqual(args[0][0], 55)
        self.assertIn("highlighted text", args[0][1])

    def test_skips_if_all_rows_already_synced(self):
        db = _make_db()
        synced_at = _NOW + timedelta(seconds=1)
        row = _make_ann(id=1, hardcover_synced_at=synced_at, updated_at=_NOW)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_id.return_value = 55

        result = sync._sync_book(1, client, _make_book())
        self.assertFalse(result)
        client.update_private_notes.assert_not_called()

    def test_syncs_if_updated_after_synced_at(self):
        db = _make_db()
        synced_at = _NOW - timedelta(hours=1)
        row = _make_ann(id=1, hardcover_synced_at=synced_at, updated_at=_NOW)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_id.return_value = 55
        client.update_private_notes.return_value = True

        result = sync._sync_book(1, client, _make_book())
        self.assertTrue(result)

    def test_skips_book_without_hardcover_details(self):
        db = _make_db()
        db.get_hardcover_details = MagicMock(return_value=None)
        sync = self._make_sync(db)
        client = MagicMock()
        self.assertFalse(sync._sync_book(1, client, _make_book()))
        client.update_private_notes.assert_not_called()

    def test_skips_book_without_hardcover_book_id(self):
        db = _make_db()
        db.get_hardcover_details = MagicMock(return_value=SimpleNamespace(hardcover_book_id=None))
        sync = self._make_sync(db)
        client = MagicMock()
        self.assertFalse(sync._sync_book(1, client, _make_book()))

    def test_skips_book_without_user_book_id(self):
        db = _make_db()
        db.get_hardcover_details = MagicMock(return_value=self._details())
        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_id.return_value = None
        self.assertFalse(sync._sync_book(1, client, _make_book()))

    def test_skips_book_without_doc_md5(self):
        db = _make_db()
        db.get_hardcover_details = MagicMock(return_value=self._details())
        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_id.return_value = 55
        book = _make_book(doc_md5="")
        self.assertFalse(sync._sync_book(1, client, book))

    def test_returns_false_if_update_private_notes_fails(self):
        db = _make_db()
        row = _make_ann(id=1, hardcover_synced_at=None)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_id.return_value = 55
        client.update_private_notes.return_value = False

        result = sync._sync_book(1, client, _make_book())
        self.assertFalse(result)

    def test_marks_all_rows_synced_after_push(self):
        db = _make_db()
        rows = [_make_ann(id=i, hardcover_synced_at=None) for i in range(3)]
        _make_session_with_rows(db, rows)
        db.get_hardcover_details = MagicMock(return_value=self._details())

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_id.return_value = 55
        client.update_private_notes.return_value = True

        sync._sync_book(1, client, _make_book())
        for row in rows:
            self.assertIsNotNone(row.hardcover_synced_at)

    def test_sync_user_not_configured_skips(self):
        from src.services.hardcover_annotation_sync import HardcoverAnnotationSync
        db = _make_db()
        sync = HardcoverAnnotationSync(db)
        result = sync.sync_user(1, {"HARDCOVER_TOKEN": "", "HARDCOVER_ENABLED": "true"})
        self.assertFalse(result)

    def test_empty_notes_block_on_no_rows(self):
        db = _make_db()
        _make_session_with_rows(db, [])
        db.get_hardcover_details = MagicMock(return_value=self._details())

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_id.return_value = 55

        result = sync._sync_book(1, client, _make_book())
        self.assertFalse(result)
        client.update_private_notes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
