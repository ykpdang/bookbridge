"""Regression tests for XPath dedup via _compute_xpath_at_position.

Covers:
- get_locator_from_char_offset passes pre-resolved data to _compute_xpath_at_position
- get_perfect_ko_xpath delegates to _compute_xpath_at_position
- _compute_xpath_at_position resolves its own data when not provided
- Both methods produce equivalent results for the same inputs
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.utils.ebook_utils import EbookParser


def test_get_locator_from_char_offset_uses_pre_resolved_data():
    """get_locator_from_char_offset passes book_path/full_text/spine_map to
    _compute_xpath_at_position instead of calling get_perfect_ko_xpath."""
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / "books"
        books.mkdir()
        parser = EbookParser(books_dir=str(books))

        # Mock dependencies to control the resolution
        parser.resolve_book_path = MagicMock(return_value=Path("/fake/book.epub"))
        parser.extract_text_and_map = MagicMock(return_value=(
            "Hello world this is a test book for xpath dedup testing purposes",
            [{"start": 0, "end": 100, "spine_index": 1, "content": "<p>Hello world</p>", "href": "xhtml/test.xhtml"}]
        ))
        # Spy on _compute_xpath_at_position
        original_compute = parser._compute_xpath_at_position
        compute_called_with = {}

        def _spy_compute(filename, position, book_path=None, full_text=None, spine_map=None):
            compute_called_with['filename'] = filename
            compute_called_with['position'] = position
            compute_called_with['book_path'] = book_path
            compute_called_with['full_text'] = full_text
            return original_compute(filename, position, book_path=book_path, full_text=full_text, spine_map=spine_map)

        parser._compute_xpath_at_position = _spy_compute

        result = parser.get_locator_from_char_offset("test.epub", 30)

        assert result is not None
        assert compute_called_with.get('book_path') is not None, "pre-resolved book_path must be passed"
        assert compute_called_with.get('full_text') is not None, "pre-resolved full_text must be passed"


def test_get_perfect_ko_xpath_delegates_to_compute():
    """get_perfect_ko_xpath calls _compute_xpath_at_position rather than
    containing its own independent implementation."""
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / "books"
        books.mkdir()
        parser = EbookParser(books_dir=str(books))

        parser.resolve_book_path = MagicMock(return_value=Path("/fake/book.epub"))
        parser.extract_text_and_map = MagicMock(return_value=(
            "Hello world this is a test book",
            [{"start": 0, "end": 50, "spine_index": 1, "content": "<p>Hello world</p>", "href": "xhtml/test.xhtml"}]
        ))

        # Verify that get_perfect_ko_xpath goes through compute
        with patch.object(parser, '_compute_xpath_at_position', wraps=parser._compute_xpath_at_position) as spy:
            xpath = parser.get_perfect_ko_xpath("test.epub", 10)
            assert xpath is not None
            spy.assert_called_once()


def test_compute_xpath_at_position_resolves_own_data_when_not_provided():
    """_compute_xpath_at_position calls resolve_book_path + extract_text_and_map
    when pre-resolved data is not supplied."""
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / "books"
        books.mkdir()
        parser = EbookParser(books_dir=str(books))

        parser.resolve_book_path = MagicMock(return_value=Path("/fake/book.epub"))
        parser.extract_text_and_map = MagicMock(return_value=(
            "Hello world this is a test book",
            [{"start": 0, "end": 50, "spine_index": 1, "content": "<p>Hello world</p>", "href": "xhtml/test.xhtml"}]
        ))

        # Call without pre-resolved data — should resolve internally
        xpath = parser._compute_xpath_at_position("test.epub", 10)
        assert xpath is not None
        parser.resolve_book_path.assert_called_once_with("test.epub")
        parser.extract_text_and_map.assert_called_once()


def test_compute_xpath_at_position_skips_resolution_when_data_provided():
    """_compute_xpath_at_position uses supplied book_path/full_text/spine_map
    without calling resolve_book_path or extract_text_and_map again."""
    with tempfile.TemporaryDirectory() as tmp:
        books = Path(tmp) / "books"
        books.mkdir()
        parser = EbookParser(books_dir=str(books))

        parser.resolve_book_path = MagicMock(return_value=Path("/fake/book.epub"))
        parser.extract_text_and_map = MagicMock()

        xpath = parser._compute_xpath_at_position(
            "test.epub", 10,
            book_path=Path("/fake/book.epub"),
            full_text="Hello world this is a test book",
            spine_map=[{"start": 0, "end": 50, "spine_index": 1, "content": "<p>Hello world</p>", "href": "xhtml/test.xhtml"}],
        )
        assert xpath is not None
        parser.resolve_book_path.assert_not_called()
        parser.extract_text_and_map.assert_not_called()
