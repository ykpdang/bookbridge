"""BookFusion UTF-16 offset mapping for KOReader xpointers.

BookFusion highlights use chapter-relative UTF-16 code-unit offsets over the
chapter body's concatenated text nodes. This module implements that coordinate
space directly from XHTML and EPUB spine content.
"""

from dataclasses import dataclass
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup
from lxml import html

logger = logging.getLogger(__name__)


def utf16_len(value: str) -> int:
    """Return JavaScript/String UTF-16 code-unit length for ``value``."""
    return len(str(value or "").encode("utf-16-le")) // 2


def codeunit_to_py_index(value: str, code_units: int) -> int:
    """Convert a UTF-16 code-unit offset into a Python string index."""
    if code_units <= 0:
        return 0
    seen = 0
    for idx, char in enumerate(value):
        size = utf16_len(char)
        if seen + size > code_units:
            return idx
        seen += size
        if seen == code_units:
            return idx + 1
    return len(value)


@dataclass
class TextNodeSpan:
    text: str
    text_parent: object
    ordinal: int
    start_units: int
    end_units: int
    xpointerable: bool = True


class BookFusionOffsetMapper:
    """Map one XHTML chapter between KOReader xpointer and BookFusion offsets."""

    def __init__(self, chapter_index: int, xhtml_content):
        self.chapter_index = int(chapter_index)
        self.docfragment_index = self.chapter_index + 1
        if isinstance(xhtml_content, bytes):
            self.tree = html.fromstring(xhtml_content)
        else:
            raw = re.sub(r"^\s*<\?xml[^>]*\?>", "", str(xhtml_content or ""))
            self.tree = html.fromstring(raw)
        self.body = self._resolve_body()
        self.spans = self._build_spans()
        self.total_units = self.spans[-1].end_units if self.spans else 0

    def xpointer_to_offset(self, xpointer: str) -> Optional[int]:
        """Convert a KOReader xpointer to a BookFusion chapter UTF-16 offset."""
        fragment, clean_path, char_offset = self._parse_xpointer(xpointer)
        if fragment is not None and fragment != self.docfragment_index:
            return None

        text_index = 1
        text_match = re.search(r"/text\(\)(?:\[(\d+)])?$", clean_path)
        if text_match:
            text_index = int(text_match.group(1) or 1)
            element_path = clean_path[:text_match.start()]
        else:
            element_path = clean_path

        element = self._find_element(element_path)
        if element is None:
            return None
        span = next(
            (s for s in self.spans if s.xpointerable and s.text_parent is element and s.ordinal == text_index),
            None,
        )
        if span is None:
            span = next((s for s in self.spans if s.xpointerable and s.text_parent is element), None)
        if span is None:
            return None
        py_offset = max(0, min(int(char_offset or 0), len(span.text)))
        return span.start_units + utf16_len(span.text[:py_offset])

    def offset_to_xpointer(self, offset: int) -> Optional[str]:
        """Convert a BookFusion chapter UTF-16 offset to a KOReader xpointer."""
        if not self.spans:
            return None
        target = max(0, min(int(offset or 0), self.total_units))
        text_spans = [span for span in self.spans if span.xpointerable]
        if not text_spans:
            return None
        span = text_spans[-1]
        for candidate in text_spans:
            if candidate.start_units <= target < candidate.end_units:
                span = candidate
                break
            if target < candidate.start_units:
                span = candidate
                target = candidate.start_units
                break
        local_units = max(0, target - span.start_units)
        py_offset = codeunit_to_py_index(span.text, local_units)
        element_path = self._element_path(span.text_parent)
        text_suffix = "text()" if span.ordinal == 1 else f"text()[{span.ordinal}]"
        return f"/body/DocFragment[{self.docfragment_index}]/{element_path}/{text_suffix}.{py_offset}"

    def text_between(self, start_offset: int, end_offset: int) -> str:
        """Return chapter text between two BookFusion UTF-16 offsets."""
        start = max(0, int(start_offset or 0))
        end = max(start, int(end_offset or 0))
        parts = []
        for span in self.spans:
            if span.end_units <= start:
                continue
            if span.start_units >= end:
                break
            local_start = codeunit_to_py_index(span.text, max(0, start - span.start_units))
            local_end = codeunit_to_py_index(span.text, min(span.end_units, end) - span.start_units)
            parts.append(span.text[local_start:local_end])
        return "".join(parts)

    def _resolve_body(self):
        bodies = self.tree.xpath("//body")
        return bodies[0] if bodies else self.tree

    def _build_spans(self) -> list[TextNodeSpan]:
        spans: list[TextNodeSpan] = []
        direct_ordinals: dict[int, int] = {}
        cursor = 0

        def add(text: str, text_parent) -> None:
            nonlocal cursor
            if text is None:
                return
            value = str(text)
            length = utf16_len(value)
            if length <= 0:
                return
            if not value.strip():
                spans.append(TextNodeSpan(text=value, text_parent=text_parent, ordinal=0,
                                          start_units=cursor, end_units=cursor + length,
                                          xpointerable=False))
                cursor += length
                return
            parent_key = id(text_parent)
            ordinal = direct_ordinals.get(parent_key, 0) + 1
            direct_ordinals[parent_key] = ordinal
            spans.append(TextNodeSpan(text=value, text_parent=text_parent, ordinal=ordinal,
                                      start_units=cursor, end_units=cursor + length))
            cursor += length

        def walk(element) -> None:
            add(element.text, element)
            for child in element:
                walk(child)
                add(child.tail, child.getparent())

        walk(self.body)
        return spans

    @staticmethod
    def _parse_xpointer(xpointer: str) -> tuple[Optional[int], str, int]:
        match = re.search(r"DocFragment\[(\d+)]", str(xpointer or ""))
        fragment = int(match.group(1)) if match else None
        path = str(xpointer or "")
        if match:
            path = path[match.end():]
        clean_path, offset = BookFusionOffsetMapper._split_char_offset(path)
        if clean_path.startswith("/"):
            clean_path = clean_path[1:]
        if clean_path.startswith("body/"):
            clean_path = clean_path[len("body/"):]
        return fragment, clean_path, offset

    @staticmethod
    def _split_char_offset(path: str) -> tuple[str, int]:
        match = re.search(r"^(.*?)(?:\.(\d+))?$", str(path or ""))
        if not match:
            return path, 0
        return match.group(1), int(match.group(2) or 0)

    def _find_element(self, element_path: str):
        path = element_path.strip("/")
        if not path:
            return self.body
        if path == "body":
            return self.body
        if path.startswith("body/"):
            path = path[len("body/"):]
        query = f"./{path}" if path else "."
        try:
            found = self.body.xpath(query)
        except Exception:
            found = []
        return found[0] if found else None

    def _element_path(self, element) -> str:
        parts = []
        current = element
        while current is not None and current is not self.body:
            tag = self._tag_name(current)
            parent = current.getparent()
            if parent is None:
                break
            siblings = [child for child in parent if self._tag_name(child) == tag]
            index = siblings.index(current) + 1 if len(siblings) > 1 else None
            parts.append(f"{tag}[{index}]" if index else tag)
            current = parent
        parts.append("body")
        return "/".join(reversed(parts))

    @staticmethod
    def _tag_name(element) -> str:
        tag = str(getattr(element, "tag", "") or "")
        return tag.rsplit("}", 1)[-1]


class BookFusionOffsetResolver:
    """Resolve BookFusion offsets for EPUB files via ``EbookParser``."""

    def __init__(self, ebook_parser):
        self._ebook_parser = ebook_parser

    def mapper_for_chapter(self, filename: str, chapter_index: int) -> Optional[BookFusionOffsetMapper]:
        try:
            book_path = self._ebook_parser.resolve_book_path(filename)
            _full_text, spine_map = self._ebook_parser.extract_text_and_map(book_path)
        except Exception as exc:
            logger.debug("BookFusion offsets: could not parse %s: %s", filename, exc)
            return None
        docfragment = int(chapter_index) + 1
        item = next((i for i in spine_map if i.get("spine_index") == docfragment), None)
        if not item:
            return None
        return BookFusionOffsetMapper(chapter_index, item.get("content") or "")

    def xpointer_to_offsets(self, filename: str, pos0: str, pos1: str = None) -> Optional[dict]:
        """Return BookFusion chapter/start/end offsets for KOReader xpointer(s)."""
        match = re.search(r"DocFragment\[(\d+)]", str(pos0 or ""))
        if not match:
            return None
        chapter_index = int(match.group(1)) - 1
        mapper = self.mapper_for_chapter(filename, chapter_index)
        if mapper is None:
            return None
        start = mapper.xpointer_to_offset(pos0)
        if start is None:
            return None
        end = mapper.xpointer_to_offset(pos1) if pos1 else None
        if end is None or end < start:
            end = start
        return {
            "chapter_index": chapter_index,
            "start_offset": start,
            "end_offset": end,
            "quote_prefix": mapper.text_between(max(0, start - 120), start),
            "quote_suffix": mapper.text_between(end, min(mapper.total_units, end + 120)),
        }

    def offsets_to_xpointers(self, filename: str, chapter_index: int, start: int, end: int) -> Optional[dict]:
        """Return KOReader pos0/pos1 and text for BookFusion offsets."""
        mapper = self.mapper_for_chapter(filename, chapter_index)
        if mapper is None:
            return None
        pos0 = mapper.offset_to_xpointer(start)
        pos1 = mapper.offset_to_xpointer(end)
        if not pos0 or not pos1:
            return None
        return {"pos0": pos0, "pos1": pos1, "text": mapper.text_between(start, end)}
