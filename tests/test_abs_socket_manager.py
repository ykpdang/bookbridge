"""Tests for ABSSocketManager — per-user ABS Socket.IO listener orchestration."""

import os
import unittest
from unittest.mock import MagicMock, patch

from src.services.abs_socket_manager import ABSSocketManager
from src.utils.user_config import _ALLOW_GLOBAL_FALLBACK_KEY


def _user(user_id, active=1):
    u = MagicMock()
    u.id = user_id
    u.active = active
    return u


def _bundle(token, configured=True, allow_global_fallback=False):
    """Build a fake per-user client bundle exposing an ABS client + credentials."""
    abs_client = MagicMock()
    abs_client.is_configured.return_value = configured
    abs_sync = MagicMock()
    abs_sync.abs_client = abs_client
    bundle = MagicMock()
    bundle.sync_clients = {"ABS": abs_sync}
    creds = {_ALLOW_GLOBAL_FALLBACK_KEY: allow_global_fallback}
    if token is not None:
        creds["ABS_KEY"] = token
    bundle.credentials = creds
    return bundle


class TestABSSocketManagerTargets(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ABS_SERVER": "http://abs.local", "ABS_KEY": "admin-token"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = MagicMock()
        self.sync = MagicMock()

    def test_global_only_when_no_registry(self):
        """Without a registry, only the global listener target is returned."""
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=None)
        targets = mgr._listener_targets()
        self.assertEqual(targets, [(None, "http://abs.local", "admin-token")])

    def test_no_targets_when_no_token_and_no_registry(self):
        """No global token and no registry yields no listeners."""
        with patch.dict(os.environ, {"ABS_KEY": ""}):
            mgr = ABSSocketManager(self.db, self.sync, user_client_registry=None)
            self.assertEqual(mgr._listener_targets(), [])

    def test_adds_per_user_listener_for_distinct_token(self):
        """A regular user with their own ABS token gets a scoped listener."""
        self.db.list_users.return_value = [_user(2)]
        registry = MagicMock()
        registry.get_clients.return_value = _bundle("caitlin-token")
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=registry)

        targets = mgr._listener_targets()

        self.assertIn((None, "http://abs.local", "admin-token"), targets)
        self.assertIn((2, "http://abs.local", "caitlin-token"), targets)
        self.assertEqual(len(targets), 2)

    def test_admin_token_not_double_listened(self):
        """An admin whose token falls back to the global key is not duplicated."""
        self.db.list_users.return_value = [_user(1)]
        registry = MagicMock()
        # Admin: no own ABS_KEY, allowed global fallback -> resolves to admin-token.
        registry.get_clients.return_value = _bundle(
            token=None, allow_global_fallback=True
        )
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=registry)

        targets = mgr._listener_targets()

        self.assertEqual(targets, [(None, "http://abs.local", "admin-token")])

    def test_skips_user_with_unconfigured_abs(self):
        """A user without a configured ABS client gets no listener."""
        self.db.list_users.return_value = [_user(3)]
        registry = MagicMock()
        registry.get_clients.return_value = _bundle("x", configured=False)
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=registry)

        self.assertEqual(mgr._listener_targets(), [(None, "http://abs.local", "admin-token")])

    def test_inactive_users_skipped(self):
        """Inactive users are not given listeners."""
        self.db.list_users.return_value = [_user(4, active=0)]
        registry = MagicMock()
        registry.get_clients.return_value = _bundle("other-token")
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=registry)

        self.assertEqual(mgr._listener_targets(), [(None, "http://abs.local", "admin-token")])
        registry.get_clients.assert_not_called()

    def test_two_users_sharing_token_deduped(self):
        """Two users with the same token only produce one extra listener."""
        self.db.list_users.return_value = [_user(5), _user(6)]
        registry = MagicMock()
        registry.get_clients.side_effect = [
            _bundle("shared-token"),
            _bundle("shared-token"),
        ]
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=registry)

        targets = mgr._listener_targets()

        tokens = [t for _, _, t in targets]
        self.assertEqual(tokens.count("shared-token"), 1)


class TestABSSocketManagerStart(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ABS_SERVER": "http://abs.local", "ABS_KEY": "admin-token"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = MagicMock()
        self.sync = MagicMock()

    def test_start_supervises_one_thread_per_target(self):
        """start() launches one supervised thread per target (global + user 2);
        listeners are constructed inside the supervisor, not in start()."""
        self.db.list_users.return_value = [_user(2)]
        registry = MagicMock()
        registry.get_clients.return_value = _bundle("caitlin-token")
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=registry)

        with patch("src.services.abs_socket_manager.threading.Thread") as MockThread:
            mgr.start()

        self.assertEqual(MockThread.call_count, 2)
        for c in MockThread.call_args_list:
            self.assertEqual(c.kwargs["target"], mgr._supervise)
        supervised_user_ids = {c.kwargs["args"][0] for c in MockThread.call_args_list}
        self.assertEqual(supervised_user_ids, {None, 2})

    def test_supervise_restarts_listener_until_stopped(self):
        """A listener that exits is re-created and restarted; the loop ends when
        stop() is signalled — the core fix for the engineio teardown death."""
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=None)
        mgr._restart_base_secs = 0
        mgr._restart_max_secs = 0
        mgr._healthy_session_secs = 0
        starts = {"n": 0}
        stops = {"n": 0}
        built = []

        class _FakeListener:
            def __init__(self, **kwargs):
                built.append(kwargs)

            def start(self_inner):
                starts["n"] += 1
                if starts["n"] >= 3:
                    mgr._stop_event.set()  # stop after the 3rd (re)start

            def stop(self_inner):
                stops["n"] += 1

        with patch("src.services.abs_socket_manager.ABSSocketListener", _FakeListener):
            mgr._supervise(None, "http://abs.local", "admin-token", "global")

        self.assertEqual(starts["n"], 3)   # initial + 2 restarts
        self.assertEqual(stops["n"], 3)    # every old debounce loop is stopped
        self.assertEqual(len(built), 3)    # a fresh listener each iteration
        self.assertTrue(all(b["user_id"] is None for b in built))

    def test_stop_signals_event_and_disconnects_current_listeners(self):
        """stop() sets the stop event and disconnects the running listener(s)."""
        mgr = ABSSocketManager(self.db, self.sync, user_client_registry=None)
        listener = MagicMock()
        mgr._current_listeners["global"] = listener

        mgr.stop()

        self.assertTrue(mgr._stop_event.is_set())
        listener.stop.assert_called_once()

    def test_start_no_targets_logs_and_returns(self):
        """With no token at all, start() launches nothing."""
        with patch.dict(os.environ, {"ABS_KEY": ""}):
            mgr = ABSSocketManager(self.db, self.sync, user_client_registry=None)
            with patch("src.services.abs_socket_manager.ABSSocketListener") as MockListener:
                mgr.start()
            MockListener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
