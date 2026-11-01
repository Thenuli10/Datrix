"""In-process, non-blocking per-project locks: a duplicate request (double-click, retry)
for a project that is already busy gets 409 instead of a second LLM call."""
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_guard = threading.Lock()
_busy: dict[int, str] = {}  # project_id -> action in progress


class ProjectBusy(Exception):
    """Another LLM-backed request for this project is still running (-> HTTP 409)."""


@contextmanager
def project_lock(project_id: int, action: str) -> Iterator[None]:
    with _guard:
        if (current := _busy.get(project_id)) is not None:
            raise ProjectBusy(f"Project {project_id} is busy ({current} in progress). Wait for it to finish.")
        _busy[project_id] = action
    try:
        yield
    finally:
        with _guard:
            _busy.pop(project_id, None)
