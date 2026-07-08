from pathlib import Path

from src.utils.cache_paths import safe_cache_path


def test_safe_cache_path_accepts_plain_basename(tmp_path):
    resolved = safe_cache_path(tmp_path, "book.epub")

    assert resolved == (tmp_path / "book.epub").resolve(strict=False)


def test_safe_cache_path_rejects_traversal_and_absolute_names(tmp_path):
    unsafe_names = [
        "",
        "../book.epub",
        "nested/book.epub",
        r"nested\book.epub",
        str(Path(tmp_path) / "outside.epub"),
        "/tmp/outside.epub",
        r"C:\tmp\outside.epub",
    ]

    for name in unsafe_names:
        assert safe_cache_path(tmp_path, name) is None
