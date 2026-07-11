"""SQL behavior tests for the BridgeSync plugin's SQLite state backend.

The DDL and every named query are extracted verbatim from
plugins/bridgesync.koplugin/bridge_sqlite_state.lua and executed against real
SQLite via Python's sqlite3, so this coverage cannot drift from the shipped
Lua. The Lua-side API contract (bind1 parameter order, step() semantics) is
covered separately by tests/lua/test_bridgesync_core.lua; this file covers
what the fake connection there cannot: that the SQL itself behaves.

Run:  pytest tests/test_bridgesync_sqlite_state.py -v
"""

import re
import sqlite3
from pathlib import Path
from unittest import TestCase

LUA_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bridgesync.koplugin"
    / "bridge_sqlite_state.lua"
)

PLUGIN = "bridgesync"


def _extract_sql_blocks() -> dict[str, str]:
    """Pull every `name = [[ ... ]]` long-string out of the Lua module."""
    text = LUA_SOURCE.read_text(encoding="utf-8")
    blocks = {}
    for match in re.finditer(r"(\w+)\s*=\s*\[\[(.*?)\]\]", text, re.DOTALL):
        blocks[match.group(1)] = match.group(2).strip()
    return blocks


SQL = _extract_sql_blocks()


def _exec_like_ljsqlite3(conn: sqlite3.Connection, commands: str) -> None:
    """Mimic lua-ljsqlite3's conn:exec(), which naively splits on ';'.

    Running each chunk through sqlite3 individually proves the schema stays
    executable on-device: a ';' inside a statement body would break here
    exactly like it would break in KOReader.
    """
    for chunk in commands.split(";"):
        chunk = chunk.strip()
        if chunk:
            conn.execute(chunk)


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _exec_like_ljsqlite3(conn, SQL["SCHEMA_SQL"])
    _exec_like_ljsqlite3(conn, SQL["INDEX_SQL"])
    conn.commit()
    return conn


class TestExtraction(TestCase):
    """The named statements the module depends on must exist in the source."""

    def test_all_expected_blocks_extracted(self):
        expected = {
            "SCHEMA_SQL",
            "INDEX_SQL",
            "get_setting",
            "set_setting",
            "delete_setting",
            "get_state_item",
            "set_state_item",
            "get_state_items_for_book",
            "get_state_books",
            "delete_all_state_items",
            "get_sync_timestamp",
            "set_sync_timestamp",
            "add_pending_session",
            "select_sessions",
            "find_mergeable_session",
            "merge_session_end",
            "prune_uploaded_sessions",
        }
        missing = expected - set(SQL)
        assert not missing, f"SQL blocks missing from Lua source: {missing}"


class TestSchema(TestCase):
    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def test_tables_exist(self):
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        assert {r[0] for r in rows} == {
            "plugin_settings",
            "plugin_state_items",
            "plugin_sync_timestamps",
            "plugin_pending_sessions",
        }

    def test_indexes_exist(self):
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        assert {r[0] for r in rows} >= {
            "idx_state_items_abs",
            "idx_settings_key",
            "idx_sync_timestamps_key",
            "idx_pending_sessions_abs",
        }

    def test_schema_is_idempotent(self):
        _exec_like_ljsqlite3(self.conn, SQL["SCHEMA_SQL"])
        _exec_like_ljsqlite3(self.conn, SQL["INDEX_SQL"])


class TestSettings(TestCase):
    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def _set(self, key, value, value_type="string"):
        self.conn.execute(SQL["set_setting"], (PLUGIN, key, value, value_type))

    def _get(self, key):
        return self.conn.execute(SQL["get_setting"], (PLUGIN, key)).fetchone()

    def test_round_trip(self):
        self._set("server_url", "http://bridge:5758")
        row = self._get("server_url")
        assert row["setting_value"] == "http://bridge:5758"
        assert row["setting_type"] == "string"

    def test_upsert_overwrites(self):
        self._set("auto_sync_on_close", "true", "boolean")
        self._set("auto_sync_on_close", "false", "boolean")
        assert self._get("auto_sync_on_close")["setting_value"] == "false"
        count = self.conn.execute(
            "SELECT COUNT(*) FROM plugin_settings WHERE setting_key='auto_sync_on_close'"
        ).fetchone()[0]
        assert count == 1

    def test_delete(self):
        self._set("stale", "x")
        self.conn.execute(SQL["delete_setting"], (PLUGIN, "stale"))
        assert self._get("stale") is None

    def test_missing_returns_nothing(self):
        assert self._get("never_set") is None


class TestStateItems(TestCase):
    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def _set(self, abs_id, key, value, value_type="string"):
        self.conn.execute(SQL["set_state_item"], (PLUGIN, abs_id, key, value, value_type))

    def test_round_trip_and_book_listing(self):
        self._set("abs-1", "filename", "book.epub")
        self._set("abs-1", "hash", "deadbeef")
        self._set("abs-2", "filename", "other.epub")

        row = self.conn.execute(SQL["get_state_item"], (PLUGIN, "abs-1", "hash")).fetchone()
        assert row["item_value"] == "deadbeef"

        items = self.conn.execute(
            SQL["get_state_items_for_book"], (PLUGIN, "abs-1")
        ).fetchall()
        assert {r["item_key"] for r in items} == {"filename", "hash"}

        books = self.conn.execute(SQL["get_state_books"], (PLUGIN,)).fetchall()
        assert [r[0] for r in books] == ["abs-1", "abs-2"]

    def test_full_replace_clears_departed_books(self):
        self._set("abs-1", "filename", "book.epub")
        self._set("abs-2", "filename", "other.epub")
        self.conn.execute(SQL["delete_all_state_items"], (PLUGIN,))
        self._set("abs-2", "filename", "other.epub")
        books = self.conn.execute(SQL["get_state_books"], (PLUGIN,)).fetchall()
        assert [r[0] for r in books] == ["abs-2"]


class TestSyncTimestamps(TestCase):
    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def _set(self, abs_id, service, sync_type, sync_hash):
        self.conn.execute(SQL["set_sync_timestamp"], (PLUGIN, abs_id, service, sync_type, sync_hash))

    def _get(self, abs_id, service, sync_type):
        return self.conn.execute(
            SQL["get_sync_timestamp"], (PLUGIN, abs_id, service, sync_type)
        ).fetchone()

    def test_round_trip_and_overwrite(self):
        self._set("*", "bridge", "statistics", "device-1:1000")
        assert self._get("*", "bridge", "statistics")["sync_hash"] == "device-1:1000"
        self._set("*", "bridge", "statistics", "device-1:2000")
        assert self._get("*", "bridge", "statistics")["sync_hash"] == "device-1:2000"

    def test_keys_are_isolated(self):
        self._set("*", "bridge", "statistics", "fp-1")
        assert self._get("*", "bridge", "annotations") is None
        assert self._get("book-1", "bridge", "statistics") is None


class TestPendingSessions(TestCase):
    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def _add(
        self,
        session_id,
        abs_id,
        start_time,
        end_time,
        duration=0,
        document_hash=None,
        session_type="EPUB",
        uploaded=0,
    ):
        self.conn.execute(
            SQL["add_pending_session"],
            (PLUGIN, session_id, abs_id, document_hash, session_type,
             start_time, end_time, duration, None, None, None, None),
        )
        if uploaded:
            self.conn.execute(
                "UPDATE plugin_pending_sessions SET uploaded=1 WHERE session_id=?",
                (session_id,),
            )

    def _find_mergeable(self, abs_id, start_time, threshold=300):
        return self.conn.execute(
            SQL["find_mergeable_session"], (PLUGIN, abs_id, start_time, threshold)
        ).fetchone()

    def test_round_trip_keeps_upload_contract_fields(self):
        self._add("s1", "abs-1", 1000, 1600, duration=600, document_hash="deadbeef")
        row = self.conn.execute(
            SQL["select_sessions"] + " ORDER BY start_time", (PLUGIN,)
        ).fetchone()
        assert row["document_hash"] == "deadbeef"
        assert row["session_type"] == "EPUB"
        assert row["duration_seconds"] == 600

    def test_duplicate_session_id_rejected(self):
        self._add("dup", "abs-1", 1000, 1100)
        with self.assertRaises(sqlite3.IntegrityError):
            self._add("dup", "abs-2", 2000, 2100)

    def test_mergeable_within_threshold(self):
        self._add("s1", "abs-1", 1000, 1100)
        found = self._find_mergeable("abs-1", 1300)
        assert found is not None and found["session_id"] == "s1"

    def test_not_mergeable_outside_threshold(self):
        self._add("s1", "abs-1", 1000, 1100)
        assert self._find_mergeable("abs-1", 1500) is None

    def test_not_mergeable_when_new_session_starts_before_previous_end(self):
        self._add("s1", "abs-1", 1000, 1100)
        assert self._find_mergeable("abs-1", 1050) is None

    def test_not_mergeable_across_books_or_uploaded(self):
        self._add("s1", "abs-1", 1000, 1100)
        self._add("s2", "abs-2", 1000, 1100, uploaded=1)
        assert self._find_mergeable("abs-2", 1200) is None
        assert self._find_mergeable("abs-3", 1200) is None

    def test_mergeable_prefers_latest_end(self):
        self._add("s1", "abs-1", 1000, 1050)
        self._add("s2", "abs-1", 1060, 1100)
        found = self._find_mergeable("abs-1", 1200)
        assert found["session_id"] == "s2"

    def test_merge_accumulates_duration(self):
        self._add("s1", "abs-1", 1000, 1100, duration=100)
        self.conn.execute(
            SQL["merge_session_end"], (1400, 30, 20.0, 100, PLUGIN, "s1")
        )
        row = self.conn.execute(
            SQL["select_sessions"] + " ORDER BY start_time", (PLUGIN,)
        ).fetchone()
        assert row["end_time"] == 1400
        assert row["duration_seconds"] == 200, (
            "merge must add reading time, not absorb the 1000-1400 span"
        )

    def test_merge_never_touches_uploaded_rows(self):
        self._add("s1", "abs-1", 1000, 1100, duration=100, uploaded=1)
        self.conn.execute(
            SQL["merge_session_end"], (1400, 30, 20.0, 100, PLUGIN, "s1")
        )
        row = self.conn.execute(
            SQL["select_sessions"] + " ORDER BY start_time", (PLUGIN,)
        ).fetchone()
        assert row["end_time"] == 1100 and row["duration_seconds"] == 100

    def test_uploaded_filter_matches_lua_suffix(self):
        self._add("s1", "abs-1", 1000, 1100)
        self._add("s2", "abs-1", 2000, 2100, uploaded=1)
        rows = self.conn.execute(
            SQL["select_sessions"] + " AND uploaded = ? ORDER BY start_time",
            (PLUGIN, 0),
        ).fetchall()
        assert [r["session_id"] for r in rows] == ["s1"]

    def test_prune_removes_only_old_uploaded(self):
        self._add("old-up", "abs-1", 1000, 1100, uploaded=1)
        self._add("new-up", "abs-1", 5000, 5100, uploaded=1)
        self._add("old-pending", "abs-1", 1000, 1200)
        self.conn.execute(SQL["prune_uploaded_sessions"], (PLUGIN, 2000))
        rows = self.conn.execute(
            SQL["select_sessions"] + " ORDER BY start_time", (PLUGIN,)
        ).fetchall()
        assert {r["session_id"] for r in rows} == {"old-pending", "new-up"}
