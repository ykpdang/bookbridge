"""
Annotation spoke stability regressions (2026-07-12 live incident).

Reproduces the BookFusion identity-churn data loss and the Readest perpetual
re-push loop observed live on 'Sea of Rust' (doc ebd9b137):

1. The BookFusion pull keyed annotation identity on BookFusion's mutable
   ``added_at`` (which is push time for bridge-created highlights and moves on
   our own PATCH) and, with ``trust_positions=True``, rewrote ``ann_key`` from
   that spoke timestamp while ``row.datetime`` stayed device-native. Devices
   hash md5(datetime|pos0), so their next complete key list omitted the
   rewritten key and the key-omission detector tombstoned the highlight
   everywhere (bridge DB rows 31/34/35 were deleted off BookFusion, Readest,
   BookOrbit and the Kobo; only the authoring Kindle kept its copy).

2. The Readest push selected rows via ``updated_at > readest_synced_at``; the
   mark-synced write itself bumps ``updated_at`` (onupdate), so every row was
   re-pushed every 15-minute cycle forever, overwriting Readest-side state
   (live log signature: identical "pushed=N pulled=0" counts each cycle).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault('DATA_DIR', 'test_data')
os.environ.setdefault('BOOKS_DIR', 'test_data')

DOC = "e" * 32

DEVICE_DT = "2026-07-11 18:36:42"
DEVICE_POS0 = "/body/DocFragment[21]/body/p[21]/span[1]/text().4"
DEVICE_POS1 = "/body/DocFragment[21]/body/p[21]/span[5]/text().12"
HIGHLIGHT_TEXT = "never heard stories about myself"
# BookFusion added_at for a bridge-created highlight = our own push time.
BF_DRIFTED_ADDED_AT = "2026-07-11T23:46:00Z"


def _device_entry(**kw):
    entry = {
        "datetime": DEVICE_DT,
        "drawer": "lighten",
        "color": "yellow",
        "posFormat": "xpointer",
        "pos0": DEVICE_POS0,
        "pos1": DEVICE_POS1,
        "text": HIGHLIGHT_TEXT,
    }
    entry.update(kw)
    return entry


def _device_book(db, changes=None, keys_of=None, keys_complete=True):
    keys = [
        {"k": db.compute_annotation_key(c["datetime"], c["pos0"]), "dt": c["datetime"]}
        for c in (keys_of or changes or [])
    ]
    return {
        "hash": DOC,
        "keys": keys,
        "keysComplete": keys_complete,
        "changes": changes or [],
    }


def _bf_item(highlight_id, added_at=BF_DRIFTED_ADDED_AT, **kw):
    item = {
        "id": highlight_id,
        "chapter_index": 20,
        "start_offset": 1691,
        "end_offset": 1826,
        "quote_text": HIGHLIGHT_TEXT,
        "added_at": added_at,
        "updated_at": added_at,
        "color": "#FFFF33",
    }
    item.update(kw)
    return item


class SpokeStabilityBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._old_data_dir = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.temp_dir
        from src.db.database_service import DatabaseService
        self.db = DatabaseService(str(Path(self.temp_dir) / 'test.db'))

    def tearDown(self):
        if hasattr(self.db, 'db_manager'):
            self.db.db_manager.close()
        if self._old_data_dir is not None:
            os.environ["DATA_DIR"] = self._old_data_dir
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_device_row(self, device_key="kindle"):
        change = _device_entry()
        self.db.exchange_koreader_annotations(
            user_id=None, device_key=device_key,
            books=[_device_book(self.db, changes=[change])],
        )
        rows = self.db.get_user_annotations_for_book(None, DOC)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def _set_bookfusion_id(self, row_id, bf_id):
        self.db.mark_spoke_annotations_uploaded(
            None, "@bookfusion", [row_id],
            server_id_field="bookfusion_highlight_id",
            version_field="bookfusion_version",
            synced_at_field="bookfusion_synced_at",
            server_ids_by_annotation_id={row_id: bf_id},
            versions_by_annotation_id={row_id: 1},
        )

    def _bookfusion_sync(self, pos0=DEVICE_POS0, pos1=DEVICE_POS1):
        from src.services.bookfusion_annotation_sync import BookFusionAnnotationSync
        sync = BookFusionAnnotationSync(self.db, ebook_parser=MagicMock())
        sync._offsets = MagicMock()
        sync._offsets.offsets_to_xpointers.return_value = {
            "pos0": pos0, "pos1": pos1, "text": HIGHLIGHT_TEXT,
        }
        return sync


class TestBookFusionIdentityStability(SpokeStabilityBase):
    """The live churn loop: BF timestamps must never enter annotation identity."""

    def test_pull_with_drifted_added_at_keeps_device_key(self):
        row = self._seed_device_row()
        device_key = self.db.compute_annotation_key(DEVICE_DT, DEVICE_POS0)
        self.assertEqual(row.ann_key, device_key)
        self._set_bookfusion_id(row.id, 101)

        sync = self._bookfusion_sync()
        client = MagicMock()
        client.pull_highlights.return_value = ([_bf_item(101)], None)
        sync._pull_for_book(None, client, "10795268", DOC, "book.epub")

        rows = self.db.get_user_annotations_for_book(None, DOC, include_deleted=True)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].deleted)
        self.assertEqual(
            rows[0].ann_key, device_key,
            "BookFusion's added_at (our own push time) leaked into ann_key — "
            "the device's next complete key list will tombstone this highlight",
        )
        self.assertEqual(rows[0].datetime, DEVICE_DT)

    def test_device_key_list_survives_bookfusion_cycle(self):
        """Full reproduction: after a BF pull cycle, the authoring device's
        complete key list must NOT read as a deletion."""
        row = self._seed_device_row(device_key="kindle")
        self._set_bookfusion_id(row.id, 101)

        sync = self._bookfusion_sync()
        client = MagicMock()
        client.pull_highlights.return_value = ([_bf_item(101)], None)
        sync._pull_for_book(None, client, "10795268", DOC, "book.epub")

        # The Kindle syncs again: complete key list with the device-computed key.
        self.db.exchange_koreader_annotations(
            user_id=None, device_key="kindle",
            books=[_device_book(self.db, keys_of=[_device_entry()])],
        )
        rows = self.db.get_user_annotations_for_book(None, DOC, include_deleted=True)
        self.assertEqual(len(rows), 1)
        self.assertFalse(
            rows[0].deleted,
            "device key-omission tombstoned a highlight the device still has "
            "(live incident: rows 31/34/35 deleted everywhere except the Kindle)",
        )

    def test_pull_unknown_id_reattaches_by_content_instead_of_duplicating(self):
        row = self._seed_device_row()
        original_key = row.ann_key
        # BookFusion re-created the highlight under a new id (e.g. after our
        # PATCH) and its offsets round-trip to a slightly different xpointer.
        drifted_pos0 = "/body/DocFragment[21]/body/p[21]/span[1]/text().5"
        sync = self._bookfusion_sync(pos0=drifted_pos0)
        client = MagicMock()
        client.pull_highlights.return_value = ([_bf_item(202)], None)
        sync._pull_for_book(None, client, "10795268", DOC, "book.epub")

        rows = self.db.get_user_annotations_for_book(None, DOC, include_deleted=True)
        self.assertEqual(len(rows), 1, "unmatched BF id must content-match, not duplicate")
        self.assertEqual(rows[0].bookfusion_highlight_id, 202)
        self.assertEqual(rows[0].ann_key, original_key)

    def test_truncated_page_skips_deletion_detection(self):
        change_a = _device_entry()
        change_b = _device_entry(datetime="2026-07-11 19:00:00",
                                 pos0="/body/DocFragment[24]/body/p[62]/span[4]/text().232",
                                 pos1="/body/DocFragment[24]/body/p[62]/span[4]/text().235",
                                 text="the")
        self.db.exchange_koreader_annotations(
            user_id=None, device_key="kindle",
            books=[_device_book(self.db, changes=[change_a, change_b])],
        )
        rows = self.db.get_user_annotations_for_book(None, DOC)
        self.assertEqual(len(rows), 2)
        self._set_bookfusion_id(rows[0].id, 101)
        self._set_bookfusion_id(rows[1].id, 102)

        sync = self._bookfusion_sync()
        client = MagicMock()
        # Server says 2 exist but the page only carried one: not a deletion.
        client.pull_highlights.return_value = ([_bf_item(101)], 2)
        sync._pull_for_book(None, client, "10795268", DOC, "book.epub")
        rows = self.db.get_user_annotations_for_book(None, DOC, include_deleted=True)
        self.assertEqual([r.deleted for r in rows], [False, False])

        # Without a Total-Count header the legacy absence semantics stand.
        client.pull_highlights.return_value = ([_bf_item(101)], None)
        sync._pull_for_book(None, client, "10795268", DOC, "book.epub")
        deleted_flags = sorted(
            (r.bookfusion_highlight_id, r.deleted)
            for r in self.db.get_user_annotations_for_book(None, DOC, include_deleted=True)
        )
        self.assertEqual(deleted_flags, [(101, False), (102, True)])


class TestTrustPositionsKeyAnchor(SpokeStabilityBase):
    """apply_spoke_annotations(trust_positions=True) key-follow must anchor to
    the row's own datetime, never the spoke entry's."""

    def test_edit_key_follows_pos0_with_row_datetime(self):
        row = self._seed_device_row()
        self.db.mark_spoke_annotations_uploaded(
            None, "@spoke-test", [row.id],
            server_id_field="bookorbit_server_id",
            version_field="bookorbit_version",
            synced_at_field="bookorbit_synced_at",
            server_ids_by_annotation_id={row.id: 301},
            versions_by_annotation_id={row.id: 1},
        )
        moved_pos0 = "/body/DocFragment[21]/body/p[22]/span[1]/text().0"
        entry = {
            "serverId": 301,
            "version": 7,
            "datetime": "2026-07-12 09:00:00",  # spoke clock, NOT the row's
            "pos0": moved_pos0,
            "pos1": DEVICE_POS1,
            "drawer": "lighten",
            "color": "yellow",
            "text": HIGHLIGHT_TEXT,
        }
        self.db.apply_spoke_annotations(
            None, DOC, "@spoke-test", adds=[], edits=[entry], deletes=[],
            trust_positions=True,
        )
        rows = self.db.get_user_annotations_for_book(None, DOC)
        self.assertEqual(rows[0].pos0, moved_pos0)
        self.assertEqual(rows[0].datetime, DEVICE_DT)
        self.assertEqual(
            rows[0].ann_key,
            self.db.compute_annotation_key(DEVICE_DT, moved_pos0),
        )


class TestReadestPushLoop(SpokeStabilityBase):
    """The perpetual re-push loop: bookkeeping writes must not re-qualify rows."""

    def _readest_sync(self):
        from src.services.readest_annotation_sync import ReadestAnnotationSync
        return ReadestAnnotationSync(self.db, ebook_parser=MagicMock())

    def _book(self):
        return SimpleNamespace(abs_id="abs-1", kosync_doc_id=DOC,
                               ebook_filename="book.epub",
                               original_ebook_filename="book.epub")

    def test_push_not_reselected_after_bookkeeping_writes(self):
        row = self._seed_device_row()
        sync = self._readest_sync()
        client = MagicMock()
        client.push_notes.return_value = True

        self.assertEqual(sync._push_for_book(None, client, self._book(), "f" * 32), 1)
        client.push_notes.assert_called_once()

        # Another spoke's bookkeeping bumps updated_at (onupdate) — the exact
        # trigger of the live 15-minute re-push loop.
        self.db.mark_spoke_annotations_uploaded(
            None, "@bookfusion", [row.id],
            server_id_field="bookfusion_highlight_id",
            version_field="bookfusion_version",
            synced_at_field="bookfusion_synced_at",
            server_ids_by_annotation_id={row.id: 101},
            versions_by_annotation_id={row.id: 1},
        )
        client.reset_mock()
        self.assertEqual(sync._push_for_book(None, client, self._book(), "f" * 32), 0)
        client.push_notes.assert_not_called()

    def test_real_content_change_is_pushed_again(self):
        self._seed_device_row()
        sync = self._readest_sync()
        client = MagicMock()
        client.push_notes.return_value = True
        self.assertEqual(sync._push_for_book(None, client, self._book(), "f" * 32), 1)

        edited = _device_entry(note="edited on device",
                               datetimeUpdated="2026-07-11 20:00:00")
        self.db.exchange_koreader_annotations(
            user_id=None, device_key="kindle",
            books=[_device_book(self.db, changes=[edited])],
        )
        client.reset_mock()
        self.assertEqual(sync._push_for_book(None, client, self._book(), "f" * 32), 1)
        notes = client.push_notes.call_args[0][0]
        self.assertEqual(notes[0]["note"], "edited on device")

    def test_pull_edit_bumps_version_once_and_reaches_devices(self):
        row = self._seed_device_row(device_key="kindle")
        sync = self._readest_sync()
        client = MagicMock()
        client.pull_notes.return_value = [{
            "id": "abc1234",
            "xpointer0": DEVICE_POS0,
            "xpointer1": DEVICE_POS1,
            "type": "annotation",
            "style": "highlight",
            "color": "yellow",
            "text": HIGHLIGHT_TEXT,
            "note": "note from readest",
            "created_at": "2026-07-11T18:36:42+00:00",
            "updated_at": "2026-07-11T21:00:00+00:00",
        }]

        sync._pull_for_book(None, client, self._book(), "f" * 32)
        rows = self.db.get_user_annotations_for_book(None, DOC)
        self.assertEqual(rows[0].note, "note from readest")
        self.assertEqual(rows[0].version, 2, "Readest edits must bump the version so devices receive them")

        # The authoring device gets the edit on its next exchange.
        result = self.db.exchange_koreader_annotations(
            user_id=None, device_key="kindle",
            books=[_device_book(self.db, keys_of=[_device_entry()])],
        )
        edits = result["books"][0]["toApply"]["edit"]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["note"], "note from readest")

        # What Readest told us is in sync with Readest: no echo push...
        push_client = MagicMock()
        push_client.push_notes.return_value = True
        self.assertEqual(sync._push_for_book(None, push_client, self._book(), "f" * 32), 0)
        push_client.push_notes.assert_not_called()

        # ...and an identical second pull must not bump again (no bump loop).
        sync._watermarks = {}
        sync._pull_for_book(None, client, self._book(), "f" * 32)
        rows = self.db.get_user_annotations_for_book(None, DOC)
        self.assertEqual(rows[0].version, 2)
        self.assertEqual(row.id, rows[0].id)

    def test_pull_add_does_not_echo_push(self):
        sync = self._readest_sync()
        client = MagicMock()
        client.pull_notes.return_value = [{
            "id": "zzz9999",
            "xpointer0": DEVICE_POS0,
            "xpointer1": DEVICE_POS1,
            "type": "annotation",
            "style": "highlight",
            "color": "yellow",
            "text": HIGHLIGHT_TEXT,
            "note": None,
            "created_at": "2026-07-11T18:36:42+00:00",
            "updated_at": "2026-07-11T18:36:42+00:00",
        }]
        sync._pull_for_book(None, client, self._book(), "f" * 32)
        rows = self.db.get_user_annotations_for_book(None, DOC)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_device, "readest")

        push_client = MagicMock()
        push_client.push_notes.return_value = True
        self.assertEqual(sync._push_for_book(None, push_client, self._book(), "f" * 32), 0)
        push_client.push_notes.assert_not_called()

        # Devices still receive the Readest-created highlight.
        result = self.db.exchange_koreader_annotations(
            user_id=None, device_key="kindle", books=[_device_book(self.db)],
        )
        self.assertEqual(len(result["books"][0]["toApply"]["add"]), 1)


if __name__ == "__main__":
    unittest.main()
