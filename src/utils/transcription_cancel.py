"""Generation-safe cooperative cancellation for transcription workers."""

import threading
from dataclasses import dataclass, field
from typing import Optional

_lock = threading.Lock()
_active: dict[str, "CancellationToken"] = {}


@dataclass(eq=False)
class CancellationToken:
    """Cancellation state owned by one specific background worker generation."""

    abs_id: str
    event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        """Ask this worker generation to stop."""
        self.event.set()

    def is_cancelled(self) -> bool:
        """Return whether this worker generation has been asked to stop."""
        return self.event.is_set()


def register_worker(abs_id: str) -> CancellationToken:
    """Register and return the cancellation token for a new worker generation."""
    token = CancellationToken(str(abs_id))
    with _lock:
        _active[token.abs_id] = token
    return token


def request_cancel(abs_id: str) -> bool:
    """Cancel the active worker for ``abs_id`` without creating sticky state."""
    if abs_id is None:
        return False
    with _lock:
        token = _active.get(str(abs_id))
    if token is None:
        return False
    token.cancel()
    return True


def is_cancelled(abs_id: str, token: Optional[CancellationToken] = None) -> bool:
    """Return whether the specified/current worker generation is cancelled."""
    if token is not None:
        return token.is_cancelled()
    if abs_id is None:
        return False
    with _lock:
        current = _active.get(str(abs_id))
    return bool(current and current.is_cancelled())


def unregister_worker(abs_id: str, token: CancellationToken) -> None:
    """Remove ``token`` only if it is still the active worker generation."""
    if abs_id is None or token is None:
        return
    with _lock:
        key = str(abs_id)
        if _active.get(key) is token:
            _active.pop(key, None)
