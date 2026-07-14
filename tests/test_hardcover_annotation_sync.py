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

    def test_update_private_notes_uses_update_user_book(self):
        c = self._client()
        c.query = MagicMock(return_value={"update_user_book": {"id": 7, "error": None}})
        self.assertTrue(c.update_private_notes(7, "some notes"))
        # Must call the real mutation, not the nonexistent *_by_pk variant.
        sent_query = c.query.call_args[0][0]
        self.assertIn("update_user_book(", sent_query)
        self.assertNotIn("update_user_books_by_pk", sent_query)

    def test_update_private_notes_failure_returns_false(self):
        c = self._client()
        c.query = MagicMock(return_value=None)
        self.assertFalse(c.update_private_notes(7, "some notes"))

    def test_update_private_notes_empty_result_false(self):
        c = self._client()
        c.query = MagicMock(return_value={"update_user_book": None})
        self.assertFalse(c.update_private_notes(7, ""))

    def test_update_private_notes_graphql_error_false(self):
        c = self._client()
        c.query = MagicMock(return_value={"update_user_book": {"id": None, "error": "denied"}})
        self.assertFalse(c.update_private_notes(7, "notes"))

    def test_get_user_book_summary_found(self):
        c = self._client()
        c.get_user_id = MagicMock(return_value=99)
        c.query = MagicMock(return_value={"user_books": [{"id": 55, "private_notes": "hi"}]})
        self.assertEqual(c.get_user_book_summary(10), (55, "hi"))

    def test_get_user_book_summary_not_found(self):
        c = self._client()
        c.get_user_id = MagicMock(return_value=99)
        c.query = MagicMock(return_value={"user_books": []})
        self.assertEqual(c.get_user_book_summary(10), (None, None))

    def test_get_user_book_summary_no_user_id(self):
        c = self._client()
        c.get_user_id = MagicMock(return_value=None)
        self.assertEqual(c.get_user_book_summary(10), (None, None))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    db = MagicMock()
    db.get_books_by_status.return_value = []
    db.get_linked_abs_ids.return_value = None
    # Version/ack change detection defaults: nothing unacked, no tombstones.
    db.get_unacked_annotation_versions.return_value = {}
    db.get_unacked_annotation_tombstones.return_value = []
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
    a.version = 1
    a.hardcover_synced_at = hardcover_synced_at
    a.updated_at = updated_at if updated_at is not None else _NOW
    return a


def _make_session_with_rows(db, rows, deleted_rows=None):
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    filter_mock = session.query.return_value.filter.return_value
    # Live-highlight query: query().filter().order_by().limit().all()
    filter_mock.order_by.return_value.limit.return_value.all.return_value = rows
    # Deleted-since query: query().filter().all()
    filter_mock.all.return_value = deleted_rows if deleted_rows is not None else []
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
        db.get_unacked_annotation_versions.return_value = {1: 1}

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (55, None)
        client.update_private_notes.return_value = True

        result = sync._sync_book(1, client, _make_book())
        self.assertTrue(result)
        client.update_private_notes.assert_called_once()
        args = client.update_private_notes.call_args
        self.assertEqual(args[0][0], 55)
        self.assertIn("highlighted text", args[0][1])

    def test_skips_if_all_rows_already_acked(self):
        db = _make_db()
        row = _make_ann(id=1, hardcover_synced_at=_NOW, updated_at=_NOW)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())
        db.get_unacked_annotation_versions.return_value = {}

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (55, None)

        result = sync._sync_book(1, client, _make_book())
        self.assertFalse(result)
        client.update_private_notes.assert_not_called()
        client.get_user_book_summary.assert_not_called()

    def test_skips_when_only_excluded_rows_are_unacked(self):
        # An unacked row that is not part of the pushed block (e.g. non-lighten)
        # must not trigger a rate-limited Hardcover call.
        db = _make_db()
        row = _make_ann(id=1, hardcover_synced_at=_NOW)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())
        db.get_unacked_annotation_versions.return_value = {99: 3}

        sync = self._make_sync(db)
        client = MagicMock()

        result = sync._sync_book(1, client, _make_book())
        self.assertFalse(result)
        client.get_user_book_summary.assert_not_called()

    def test_syncs_if_content_version_above_ack(self):
        db = _make_db()
        row = _make_ann(id=1, hardcover_synced_at=_NOW - timedelta(hours=1), updated_at=_NOW)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())
        db.get_unacked_annotation_versions.return_value = {1: 2}

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (55, None)
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
        row = _make_ann(id=1, hardcover_synced_at=None)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())
        db.get_unacked_annotation_versions.return_value = {1: 1}
        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (None, None)
        self.assertFalse(sync._sync_book(1, client, _make_book()))
        client.update_private_notes.assert_not_called()

    def test_skips_book_without_doc_md5(self):
        db = _make_db()
        db.get_hardcover_details = MagicMock(return_value=self._details())
        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (55, None)
        book = _make_book(doc_md5="")
        self.assertFalse(sync._sync_book(1, client, book))

    def test_returns_false_if_update_private_notes_fails(self):
        db = _make_db()
        row = _make_ann(id=1, hardcover_synced_at=None)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())
        db.get_unacked_annotation_versions.return_value = {1: 1}

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (55, None)
        client.update_private_notes.return_value = False

        result = sync._sync_book(1, client, _make_book())
        self.assertFalse(result)
        db.ack_annotation_versions.assert_not_called()

    def test_acks_all_rows_after_push(self):
        db = _make_db()
        rows = [_make_ann(id=i, hardcover_synced_at=None) for i in range(3)]
        for row in rows:
            row.version = 1
        _make_session_with_rows(db, rows)
        db.get_hardcover_details = MagicMock(return_value=self._details())
        db.get_unacked_annotation_versions.return_value = {0: 1, 1: 1, 2: 1}

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (55, None)
        client.update_private_notes.return_value = True

        sync._sync_book(1, client, _make_book())
        for row in rows:
            self.assertIsNotNone(row.hardcover_synced_at)
        db.ack_annotation_versions.assert_called_once()
        kwargs = db.ack_annotation_versions.call_args
        self.assertEqual(kwargs.kwargs["versions_by_id"], {0: 1, 1: 1, 2: 1})

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
        client.get_user_book_summary.return_value = (55, None)

        result = sync._sync_book(1, client, _make_book())
        self.assertFalse(result)
        client.update_private_notes.assert_not_called()

    def test_propagates_deletion_when_only_deletion_changed(self):
        # All live highlights are already acked, but one previously-pushed row
        # was tombstoned — the block must still be rewritten so it disappears
        # remotely, and the tombstone acked so it doesn't retrigger next cycle.
        db = _make_db()
        live = _make_ann(id=1, hardcover_synced_at=_NOW, updated_at=_NOW)
        _make_session_with_rows(db, [live])
        db.get_hardcover_details = MagicMock(return_value=self._details())
        db.get_unacked_annotation_versions.return_value = {}
        db.get_unacked_annotation_tombstones.return_value = [2]

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (55, None)
        client.update_private_notes.return_value = True

        result = sync._sync_book(1, client, _make_book())
        self.assertTrue(result)
        client.update_private_notes.assert_called_once()
        kwargs = db.ack_annotation_versions.call_args
        self.assertEqual(kwargs.kwargs["deleted_ids"], [2])

    def test_preserves_user_private_notes_outside_managed_block(self):
        db = _make_db()
        row = _make_ann(id=1, text="my highlight", hardcover_synced_at=None)
        _make_session_with_rows(db, [row])
        db.get_hardcover_details = MagicMock(return_value=self._details())
        db.get_unacked_annotation_versions.return_value = {1: 1}

        sync = self._make_sync(db)
        client = MagicMock()
        client.get_user_book_summary.return_value = (55, "My own private thoughts.")
        client.update_private_notes.return_value = True

        sync._sync_book(1, client, _make_book())
        written = client.update_private_notes.call_args[0][1]
        self.assertIn("My own private thoughts.", written)
        self.assertIn("my highlight", written)


class TestHardcoverSpliceManaged(unittest.TestCase):
    def setUp(self):
        from src.services.hardcover_annotation_sync import HardcoverAnnotationSync
        self.sync = HardcoverAnnotationSync.__new__(HardcoverAnnotationSync)
        from src.services import hardcover_annotation_sync as mod
        self.START = mod._MANAGED_START
        self.END = mod._MANAGED_END

    def test_appends_block_when_no_existing_managed_region(self):
        out = self.sync._splice_managed("user text", "BLOCK")
        self.assertTrue(out.startswith("user text"))
        self.assertIn(self.START, out)
        self.assertIn("BLOCK", out)

    def test_replaces_existing_managed_region_preserving_surroundings(self):
        existing = f"top\n\n{self.START}\nOLD\n{self.END}\n\nbottom"
        out = self.sync._splice_managed(existing, "NEW")
        self.assertIn("top", out)
        self.assertIn("bottom", out)
        self.assertIn("NEW", out)
        self.assertNotIn("OLD", out)

    def test_empty_block_removes_managed_region_keeps_user_text(self):
        existing = f"keep me\n\n{self.START}\nOLD\n{self.END}"
        out = self.sync._splice_managed(existing, "")
        self.assertIn("keep me", out)
        self.assertNotIn(self.START, out)
        self.assertNotIn("OLD", out)


if __name__ == "__main__":
    unittest.main()
