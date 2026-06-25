"""Match routes enqueue tracker auto-match to a background worker instead of
blocking the response on EPUB downloads + the Ollama judge."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.web_server as ws


def _drain():
    """Wait for the (single, daemon) worker to finish all queued jobs."""
    ws._TRACKER_AUTOMATCH_QUEUE.join()


class TestDeferredTrackerAutomatch(unittest.TestCase):
    def test_enqueue_runs_both_trackers(self):
        book = SimpleNamespace(abs_id="abs1")
        hc = MagicMock(); hc.is_configured.return_value = True
        sg = MagicMock(); sg.is_configured.return_value = True

        ws._enqueue_tracker_automatch({"Hardcover": hc, "StoryGraph": sg}, book)
        _drain()

        hc._automatch_hardcover.assert_called_once_with(book)
        sg._automatch_storygraph.assert_called_once_with(book)

    def test_unconfigured_client_skipped(self):
        book = SimpleNamespace(abs_id="abs2")
        hc = MagicMock(); hc.is_configured.return_value = False
        sg = MagicMock(); sg.is_configured.return_value = True

        ws._enqueue_tracker_automatch({"Hardcover": hc, "StoryGraph": sg}, book)
        _drain()

        hc._automatch_hardcover.assert_not_called()
        sg._automatch_storygraph.assert_called_once_with(book)

    def test_one_failure_does_not_block_the_other(self):
        book = SimpleNamespace(abs_id="abs3")
        hc = MagicMock(); hc.is_configured.return_value = True
        hc._automatch_hardcover.side_effect = RuntimeError("boom")
        sg = MagicMock(); sg.is_configured.return_value = True

        ws._enqueue_tracker_automatch({"Hardcover": hc, "StoryGraph": sg}, book)
        _drain()

        hc._automatch_hardcover.assert_called_once_with(book)
        sg._automatch_storygraph.assert_called_once_with(book)  # still ran

    def test_no_book_is_noop(self):
        # Should not start the worker or raise.
        ws._enqueue_tracker_automatch({"Hardcover": MagicMock()}, None)
        _drain()


if __name__ == "__main__":
    unittest.main()
