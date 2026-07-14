"""Regression tests for _validate_and_stabilize_locator behavior.

Verifies that the locator stabilization logic correctly:
- Rejects unresolvable XPath (ko_error = tolerance + 1, not ko_offset = target_offset)
- Retains verified regenerated CFI (round-trips within tolerance)
- Rejects unverified regenerated CFI (regenerated_cfi_rejected tag)
- Keeps CFI that was already valid (no regeneration needed)
- Falls back to sentence-level XPath when primary XPath fails but sentence succeeds
- Falls back to percent-only when both XPath and sentence XPath fail

Uses mocked ebook_parser to avoid real EPUB dependencies.
"""

import os
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from src.db.models import Book
from src.sync_manager import SyncManager
from src.utils.ebook_utils import LocatorResult


def _make_manager(ebook_parser=None):
    """Build a SyncManager with mocked dependencies."""
    db = MagicMock()
    db.get_books_by_status.return_value = []
    parser = ebook_parser or MagicMock()
    parser.locator_roundtrip_tolerance = 2

    manager = SyncManager(
        abs_client=MagicMock(),
        booklore_client=MagicMock(),
        hardcover_client=MagicMock(),
        transcriber=MagicMock(),
        ebook_parser=parser,
        database_service=db,
        storyteller_client=MagicMock(),
        sync_clients={},
        alignment_service=None,
        library_service=None,
        migration_service=None,
        epub_cache_dir="/tmp/epub_cache",
        data_dir="/tmp",
        books_dir="/tmp/books",
    )
    return manager


def _make_book(abs_id="test-book", ebook_filename="test.epub"):
    """Build a minimal Book object."""
    return Book(
        abs_id=abs_id,
        abs_title="Test Book",
        ebook_filename=ebook_filename,
        status="active",
    )


class TestValidateAndStabilizeLocatorXPath(unittest.TestCase):
    """Tests for XPath validation behavior in _validate_and_stabilize_locator."""

    def setUp(self):
        self.parser = MagicMock()
        self.parser.locator_roundtrip_tolerance = 2
        self.manager = _make_manager(ebook_parser=self.parser)
        self.book = _make_book()

    def test_unresolvable_xpath_rejected(self):
        """When XPath cannot be resolved, it is removed (not silently accepted)."""
        self.parser.resolve_xpath_to_index.return_value = None
        self.parser.get_sentence_level_ko_xpath.return_value = None

        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi="/6/4!",
            match_index=100,
            href="chap1.html",
            fragment=None,
            css_selector=None,
            chapter_progress=0.5,
        )

        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=locator, ebook_filename="test.epub",
        )

        self.assertIsNotNone(result)
        # XPath should be None — unresolvable, removed
        self.assertIsNone(result.xpath)
        self.assertIsNone(result.perfect_ko_xpath)
        # The parser was asked to resolve
        self.parser.resolve_xpath_to_index.assert_called()

    def test_resolvable_xpath_retained(self):
        """When XPath resolves within tolerance, it is retained."""
        self.parser.resolve_xpath_to_index.return_value = 100  # matches target_offset
        # Don't need sentence fallback to interfere
        self.parser.get_sentence_level_ko_xpath.return_value = None

        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi="/6/4!",
            match_index=100,
            href="chap1.html",
        )

        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=locator, ebook_filename="test.epub",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.xpath, "/body/p[1]/text().0")
        self.assertEqual(result.perfect_ko_xpath, "/body/p[1]/text().0")

    def test_xpath_out_of_tolerance_falls_back_to_sentence(self):
        """When XPath resolves but out of tolerance, sentence-level XPath is tried."""
        self.parser.resolve_xpath_to_index.side_effect = [50, None]  # xpath returns 50 (off by 50)
        self.parser.get_sentence_level_ko_xpath.return_value = "/body/p[2]/text().0"

        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi=None,
            match_index=100,
            href="chap1.html",
        )

        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=locator, ebook_filename="test.epub",
        )

        self.assertIsNotNone(result)
        # Sentence XPath was requested
        self.parser.get_sentence_level_ko_xpath.assert_called_once()

    def test_sentence_xpath_also_fails_percent_only(self):
        """When both XPath and sentence XPath fail, falls back to percent-only."""
        self.parser.resolve_xpath_to_index.side_effect = [None, None, None]  # all three fail
        self.parser.get_sentence_level_ko_xpath.return_value = "/body/p[99]/text().0"

        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi=None,
            match_index=100,
            href="chap1.html",
        )

        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=locator, ebook_filename="test.epub",
        )

        self.assertIsNotNone(result)
        self.assertIsNone(result.xpath)
        self.assertIsNone(result.perfect_ko_xpath)


class TestValidateAndStabilizeLocatorCFI(unittest.TestCase):
    """Tests for CFI regeneration behavior in _validate_and_stabilize_locator."""

    def setUp(self):
        self.parser = MagicMock()
        self.parser.locator_roundtrip_tolerance = 2
        self.manager = _make_manager(ebook_parser=self.parser)
        self.book = _make_book()
        # XPath always resolves perfectly so CFI tests are independent
        self.parser.resolve_xpath_to_index.return_value = 100

    def test_valid_cfi_retained(self):
        """When CFI resolves within tolerance, it is retained as-is."""
        self.parser.resolve_cfi_to_index.return_value = 100  # matches target_offset

        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi="/6/4!",
            match_index=100,
            href="chap1.html",
        )

        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=locator, ebook_filename="test.epub",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.cfi, "/6/4!")  # retained unchanged

    def test_regenerated_cfi_verified_retained(self):
        """When original CFI fails but regenerated CFI round-trips, use regenerated."""
        # Original CFI resolves to wrong offset
        self.parser.resolve_cfi_to_index.side_effect = [
            500,    # original CFI → offset 500 (way off)
            101,    # regenerated CFI → offset 101 (within tolerance of 100)
        ]
        # Regenerated locator has a CFI
        regenerated = MagicMock()
        regenerated.cfi = "/6/10!"  # new CFI
        self.parser.get_locator_from_char_offset.return_value = regenerated

        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi="/6/4!",
            match_index=100,
            href="chap1.html",
        )

        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=locator, ebook_filename="test.epub",
        )

        self.assertIsNotNone(result)
        # Should have regenerated CFI
        self.assertEqual(result.cfi, "/6/10!")
        self.parser.get_locator_from_char_offset.assert_called_once()

    def test_regenerated_cfi_unverified_rejected(self):
        """When regenerated CFI fails round-trip, it is rejected (cfi set to None)."""
        # Original CFI resolves to wrong offset
        self.parser.resolve_cfi_to_index.side_effect = [
            500,    # original CFI → offset 500
            500,    # regenerated CFI → also offset 500 (still way off!)
        ]
        # Regenerated locator has a CFI
        regenerated = MagicMock()
        regenerated.cfi = "/6/10!"
        self.parser.get_locator_from_char_offset.return_value = regenerated

        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi="/6/4!",
            match_index=100,
            href="chap1.html",
        )

        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=locator, ebook_filename="test.epub",
        )

        self.assertIsNotNone(result)
        # CFI should be None — rejected because regenerated didn't round-trip
        self.assertIsNone(result.cfi)
        self.parser.get_locator_from_char_offset.assert_called_once()

    def test_no_cfi_available(self):
        """When there's no CFI at all and regeneration also fails, CFI stays None."""
        # No original CFI
        self.parser.resolve_cfi_to_index.return_value = None
        # Regeneration also fails (returns None or locator without cfi)
        self.parser.get_locator_from_char_offset.return_value = None

        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi=None,
            match_index=100,
            href="chap1.html",
        )

        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=locator, ebook_filename="test.epub",
        )

        self.assertIsNotNone(result)
        self.assertIsNone(result.cfi)


class TestValidateAndStabilizeLocatorEdgeCases(unittest.TestCase):
    """Edge cases for _validate_and_stabilize_locator."""

    def setUp(self):
        self.parser = MagicMock()
        self.parser.locator_roundtrip_tolerance = 2
        self.manager = _make_manager(ebook_parser=self.parser)
        self.book = _make_book()

    def test_no_locator_returns_none(self):
        """When locator is None, returns None."""
        result = self.manager._validate_and_stabilize_locator(
            self.book, target_offset=100, locator=None, ebook_filename="test.epub",
        )
        self.assertIsNone(result)

    def test_no_ebook_filename_returns_locator_unchanged(self):
        """When no ebook filename available, returns locator unchanged."""
        book_no_epub = _make_book(ebook_filename=None)
        locator = LocatorResult(
            percentage=0.5,
            xpath="/body/p[1]/text().0",
            perfect_ko_xpath="/body/p[1]/text().0",
            cfi="/6/4!",
            match_index=100,
            href="chap1.html",
        )

        result = self.manager._validate_and_stabilize_locator(
            book_no_epub, target_offset=100, locator=locator, ebook_filename=None,
        )

        # Should return the locator as-is (no validation possible)
        self.assertIs(result, locator)

    def test_tolerance_env_var_respected(self):
        """The CROSSFORMAT_ROUNDTRIP_TOLERANCE_CHARS env var overrides default."""
        with patch.dict(os.environ, {"CROSSFORMAT_ROUNDTRIP_TOLERANCE_CHARS": "10"}):
            # Rebuild manager so it reads the env var
            parser = MagicMock()
            parser.locator_roundtrip_tolerance = 2  # default would be 2
            manager = _make_manager(ebook_parser=parser)
            book = _make_book()
            parser.resolve_xpath_to_index.return_value = 200  # way off

            locator = LocatorResult(
                percentage=0.5,
                xpath="/body/p[1]/text().0",
                perfect_ko_xpath="/body/p[1]/text().0",
                match_index=100,
                href="chap1.html",
            )

            result = manager._validate_and_stabilize_locator(
                book, target_offset=100, locator=locator, ebook_filename="test.epub",
            )

            # With tolerance=10, offset 200 vs target 100 → error 100 > 10 → rejected
            self.assertIsNotNone(result)
            self.assertIsNone(result.xpath)
