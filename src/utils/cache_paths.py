"""Helpers for safe filename-only cache paths."""

from pathlib import Path, PurePath, PureWindowsPath


def safe_cache_path(cache_dir, filename: str) -> Path | None:
    """Return ``cache_dir / filename`` only when filename is a plain basename.

    Cache filenames may come from provider metadata or stored book rows. Refuse
    absolute paths and traversal on both POSIX and Windows path conventions so a
    cache lookup/write/delete cannot escape the cache directory.
    """
    raw = str(filename or "").strip()
    if not raw or raw in {".", ".."}:
        return None
    if PurePath(raw).name != raw or PureWindowsPath(raw).name != raw:
        return None

    root = Path(cache_dir).resolve(strict=False)
    candidate = (root / raw).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
