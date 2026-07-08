import re
from pathlib import Path
from typing import Optional

from lxml import html


class GrimmoryCFIResolver:
    """Small EPUB CFI/xpointer bridge modeled on grimmory.koplugin.

    It supports the KOReader xpointer shape stored by the bridge and Grimmory's
    EPUB CFI range shape. Conversion is intentionally fail-closed: callers should
    retry later rather than mark an annotation synced when an anchor cannot be
    resolved.
    """

    _DOC_FRAGMENT_RE = re.compile(r"^/body/DocFragment\[(\d+)](.+)$")
    _CFI_RANGE_RE = re.compile(r"^epubcfi\(([^,)]*),([^,)]*),([^,)]*)\)$")

    def __init__(self, ebook_parser, book_path):
        self.ebook_parser = ebook_parser
        self.book_path = Path(book_path)
        self.full_text, self.spine_map = ebook_parser.extract_text_and_map(self.book_path)

    @staticmethod
    def _element_children(parent):
        return [child for child in list(parent) if isinstance(getattr(child, "tag", None), str)]

    @staticmethod
    def _local_name(element) -> str:
        tag = getattr(element, "tag", "") or ""
        return tag.split("}", 1)[-1].lower()

    def _spine_item(self, fragment_index: int) -> dict:
        for item in self.spine_map:
            if int(item.get("spine_index") or 0) == int(fragment_index):
                return item
        raise ValueError(f"DocFragment[{fragment_index}] not found in EPUB spine")

    def _parse_xpointer(self, xpointer: str):
        match = self._DOC_FRAGMENT_RE.match(str(xpointer or ""))
        if not match:
            raise ValueError(f"Unsupported KOReader xpointer: {xpointer!r}")
        fragment_index = int(match.group(1))
        relative_path = match.group(2)
        clean_xpath, offset = self.ebook_parser._split_xpath_char_offset(relative_path)
        if clean_xpath.startswith("/"):
            clean_xpath = "." + clean_xpath
        return fragment_index, clean_xpath, int(offset or 0)

    def _resolve_xpointer_element(self, xpointer: str):
        fragment_index, clean_xpath, offset = self._parse_xpointer(xpointer)
        item, _tree, element = self.ebook_parser._resolve_xpath_target_node(
            self.book_path.name,
            self.spine_map,
            fragment_index,
            clean_xpath,
        )
        if item is None or element is None:
            raise ValueError(f"Could not resolve xpointer: {xpointer!r}")
        return int(item["spine_index"]), element, offset

    def _element_to_cfi_steps(self, element) -> list[str]:
        chain = []
        current = element
        while current is not None and self._local_name(current) not in ("", "html"):
            chain.append(current)
            current = current.getparent()

        steps = []
        for node in reversed(chain):
            parent = node.getparent()
            if parent is None:
                continue
            siblings = self._element_children(parent)
            if node not in siblings:
                continue
            steps.append(str((siblings.index(node) + 1) * 2))
        if not steps:
            steps = ["4"]
        return steps

    def xpointer_to_cfi(self, xpointer: str) -> str:
        fragment_index, element, offset = self._resolve_xpointer_element(xpointer)
        local_steps = self._element_to_cfi_steps(element)
        local_steps.append(f"1:{max(0, int(offset or 0))}")
        spine_step = fragment_index * 2
        return f"epubcfi(/6/{spine_step}!/{'/'.join(local_steps)})"

    @staticmethod
    def as_cfi_range(cfi_start: str, cfi_end: str) -> str:
        bare_start = cfi_start.removeprefix("epubcfi(").removesuffix(")")
        bare_end = cfi_end.removeprefix("epubcfi(").removesuffix(")")
        prefix = ""
        start_parts = bare_start.split("/")
        end_parts = bare_end.split("/")
        shared = []
        for a, b in zip(start_parts, end_parts):
            if a != b:
                break
            shared.append(a)
        if shared:
            prefix = "/".join(shared)
        if not prefix:
            return f"epubcfi({bare_start},,{bare_end})"
        return f"epubcfi({prefix},{bare_start[len(prefix):]},{bare_end[len(prefix):]})"

    def xpointer_range_to_cfi(self, xpointer_start: str, xpointer_end: Optional[str]) -> str:
        cfi_start = self.xpointer_to_cfi(xpointer_start)
        cfi_end = self.xpointer_to_cfi(xpointer_end or xpointer_start)
        return self.as_cfi_range(cfi_start, cfi_end)

    @classmethod
    def split_cfi_range(cls, cfi: str):
        match = cls._CFI_RANGE_RE.match(str(cfi or ""))
        if not match:
            raise ValueError(f"Unsupported Grimmory CFI range: {cfi!r}")
        root, start, end = match.groups()
        return f"epubcfi({root}{start})", f"epubcfi({root}{end})"

    @staticmethod
    def _parse_cfi_point(cfi: str):
        bare = str(cfi or "").strip()
        bare = bare.removeprefix("epubcfi(").removesuffix(")")
        global_path, _, local_path = bare.partition("!")
        fragment_index = 1
        match = re.search(r"^/6/(\d+)", global_path)
        if match:
            fragment_index = int(match.group(1)) // 2
        local = local_path or global_path
        parts = [part for part in local.strip("/").split("/") if part]
        return fragment_index, parts

    def _cfi_point_to_xpointer(self, cfi: str) -> str:
        fragment_index, parts = self._parse_cfi_point(cfi)
        item = self._spine_item(fragment_index)
        tree = html.fromstring(item["content"])
        current = tree
        offset = 0
        text_step = False

        for part in parts:
            if ":" in part:
                step, offset_text = part.split(":", 1)
                try:
                    offset = int(offset_text or 0)
                except ValueError:
                    offset = 0
            else:
                step = part
            try:
                step_num = int(re.sub(r"\[.*?]", "", step))
            except ValueError:
                continue
            if step_num % 2 == 1:
                text_step = True
                continue
            children = self._element_children(current)
            index = (step_num // 2) - 1
            if index < 0 or index >= len(children):
                raise ValueError(f"CFI step {step_num} does not resolve in fragment {fragment_index}")
            current = children[index]

        xpath = self.ebook_parser._build_xpath(current)
        suffix = "/text()" if text_step else "/text()"
        return f"/body/DocFragment[{fragment_index}]/{xpath}{suffix}.{max(0, offset)}"

    def cfi_range_to_xpointers(self, cfi: str):
        cfi_start, cfi_end = self.split_cfi_range(cfi)
        return self._cfi_point_to_xpointer(cfi_start), self._cfi_point_to_xpointer(cfi_end)
