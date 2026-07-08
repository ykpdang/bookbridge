"""
Rich progress metadata, Phase 2: freshness guards in leader selection.

Guard 1 (staleness suppression): a client whose service_updated_at has not
advanced past the persisted value is a stale re-reading, not fresh movement —
it cannot be a delta candidate.

Guard 2 (rollback veto): a delta candidate sitting materially behind a peer
whose service timestamp is materially newer cannot lead.

Both guards no-op without timestamps and are disabled by SYNC_FRESHNESS_GUARDS.
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sync_clients.sync_client_interface import ServiceState
from src.sync_manager import SyncManager


def _state(current: dict, previous_pct: float = 0.0, delta: float = 0.0) -> ServiceState:
    return ServiceState(
        current=current,
        previous_pct=previous_pct,
        delta=delta,
        threshold=0.01,
        is_configured=True,
        display=("X", "{prev:.2%}->{curr:.2%}"),
        value_formatter=lambda v: f"{v:.4%}",
    )


def _manager(delta_clients):
    manager = SyncManager.__new__(SyncManager)

    class _Client:
        def can_be_leader(self):
            return True

    manager.sync_clients = {name: _Client() for name in ("ABS", "KoSync", "BookLore")}
    manager._has_significant_delta = MagicMock(
        side_effect=lambda name, cfg, book: name in delta_clients
    )
    manager._normalize_for_cross_format_comparison = MagicMock(return_value=None)
    manager.sync_delta_between_clients = 0.01
    return manager


def _book():
    return SimpleNamespace(duration=10000, transcript_file=None, sync_mode="audiobook")


class FreshnessGuardBase(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SYNC_FRESHNESS_GUARDS", None)
        os.environ.pop("SYNC_ROLLBACK_VETO_SECONDS", None)

    tearDown = setUp


class TestStalenessSuppression(FreshnessGuardBase):
    def test_stale_reading_cannot_lead_alone(self):
        """The #290 shape: a static value re-surfaces as a 'fresh' delta, but the
        service's own timestamp says nothing changed — suppressed; furthest wins."""
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({"pct": 0.60, "ts": 6000.0}),
            "KoSync": _state({
                "pct": 0.53, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,
                "_service_prev_updated_at": 1751400000.0,  # unchanged since last sync
            }, previous_pct=0.0),
        }
        leader, leader_pct = manager._determine_leader(config, _book(), "abs-1", "book")
        # KoSync suppressed; fallback picks the furthest (ABS), never the stale 53%.
        self.assertEqual(leader, "ABS")
        self.assertEqual(leader_pct, 0.60)

    def test_advanced_timestamp_leads_normally(self):
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({"pct": 0.50, "ts": 5000.0}),
            "KoSync": _state({
                "pct": 0.53, "xpath": "/body/x",
                "service_updated_at": 1751400600.0,
                "_service_prev_updated_at": 1751400000.0,  # advanced → genuine movement
            }),
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "KoSync")

    def test_missing_timestamps_fall_back_to_current_behavior(self):
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({"pct": 0.60, "ts": 6000.0}),
            "KoSync": _state({"pct": 0.53, "xpath": "/body/x"}),  # no rich metadata
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "KoSync")  # single-delta fast path, unchanged

    def test_kill_switch_disables_suppression(self):
        os.environ["SYNC_FRESHNESS_GUARDS"] = "false"
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({"pct": 0.60, "ts": 6000.0}),
            "KoSync": _state({
                "pct": 0.53, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,
                "_service_prev_updated_at": 1751400000.0,
            }),
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "KoSync")

    def test_suppression_leaves_other_candidates_untouched(self):
        manager = _manager(delta_clients={"KoSync", "BookLore"})
        config = {
            "ABS": _state({"pct": 0.10, "ts": 1000.0}),
            "KoSync": _state({
                "pct": 0.53, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,
                "_service_prev_updated_at": 1751400000.0,  # stale
            }),
            "BookLore": _state({
                "pct": 0.40, "cfi": "epubcfi(/6/8!)",
                "service_updated_at": 1751400900.0,
                "_service_prev_updated_at": 1751400000.0,  # fresh
            }),
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "BookLore")


class TestRollbackVeto(FreshnessGuardBase):
    def test_behind_and_older_candidate_is_vetoed(self):
        """Catch-up shape: both moved while the bridge was down; the behind
        client's position is >10 min older — the newer, further one must win."""
        manager = _manager(delta_clients={"KoSync", "BookLore"})
        config = {
            "KoSync": _state({
                "pct": 0.40, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,
                "_service_prev_updated_at": 1751000000.0,
            }),
            "BookLore": _state({
                "pct": 0.45, "cfi": "epubcfi(/6/8!)",
                "service_updated_at": 1751401000.0,  # 1000s newer
                "_service_prev_updated_at": 1751000000.0,
            }),
        }
        leader, leader_pct = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "BookLore")
        self.assertEqual(leader_pct, 0.45)

    def test_behind_single_delta_candidate_cannot_use_fast_path(self):
        """A lone stale-behind delta would normally win the single-delta fast
        path and roll everyone back — the veto blocks its candidacy."""
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({
                "pct": 0.60, "ts": 6000.0,
                "service_updated_at": 1751401000.0,
            }),
            "KoSync": _state({
                "pct": 0.40, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,  # 1000s older than ABS
                "_service_prev_updated_at": 1751399000.0,  # advanced → not stale-suppressed
            }),
        }
        leader, leader_pct = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "ABS")
        self.assertEqual(leader_pct, 0.60)

    def test_genuine_reread_with_newer_timestamp_is_not_vetoed(self):
        """User deliberately jumped back and kept reading: behind but NEWER —
        the veto must not fire."""
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({
                "pct": 0.60, "ts": 6000.0,
                "service_updated_at": 1751400000.0,
            }),
            "KoSync": _state({
                "pct": 0.40, "xpath": "/body/x",
                "service_updated_at": 1751401000.0,  # newer than ABS
                "_service_prev_updated_at": 1751399000.0,
            }),
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "KoSync")

    def test_within_tolerance_is_not_vetoed(self):
        """Timestamp gaps inside the tolerance window are treated as clock skew."""
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({
                "pct": 0.60, "ts": 6000.0,
                "service_updated_at": 1751400500.0,  # only 500s newer (< 600 default)
            }),
            "KoSync": _state({
                "pct": 0.40, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,
                "_service_prev_updated_at": 1751399000.0,
            }),
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "KoSync")

    def test_tolerance_is_configurable(self):
        os.environ["SYNC_ROLLBACK_VETO_SECONDS"] = "100"
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({
                "pct": 0.60, "ts": 6000.0,
                "service_updated_at": 1751400500.0,  # 500s newer > 100s tolerance
            }),
            "KoSync": _state({
                "pct": 0.40, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,
                "_service_prev_updated_at": 1751399000.0,
            }),
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "ABS")

    def test_forward_movement_is_never_vetoed(self):
        """The candidate is AHEAD — timestamps are irrelevant; leads as today."""
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({
                "pct": 0.40, "ts": 4000.0,
                "service_updated_at": 1751401000.0,  # newer but behind
            }),
            "KoSync": _state({
                "pct": 0.60, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,
                "_service_prev_updated_at": 1751399000.0,
            }),
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "KoSync")

    def test_missing_peer_timestamp_disables_veto(self):
        manager = _manager(delta_clients={"KoSync"})
        config = {
            "ABS": _state({"pct": 0.60, "ts": 6000.0}),  # no service timestamp
            "KoSync": _state({
                "pct": 0.40, "xpath": "/body/x",
                "service_updated_at": 1751400000.0,
                "_service_prev_updated_at": 1751399000.0,
            }),
        }
        leader, _ = manager._determine_leader(config, _book(), "abs-1", "book")
        self.assertEqual(leader, "KoSync")  # old behavior preserved


if __name__ == '__main__':
    unittest.main()
