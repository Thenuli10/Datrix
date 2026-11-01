"""In-process background jobs + per-run log bus for SSE (PLAN.md §1, §5)."""
import asyncio
import logging
import threading
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DONE = "\x00__done__"


class LogBus:
    """Fan-out of run log lines to SSE subscribers; also appends to the run's logs.txt.

    publish() may be called from worker threads; subscribers live on the event loop.
    """

    def __init__(self) -> None:
        self._subs: dict[int, list[asyncio.Queue[str]]] = defaultdict(list)
        self._files: dict[int, Path] = {}
        self._history: dict[int, list[str]] = defaultdict(list)
        self._lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    def attach_file(self, run_id: int, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._files[run_id] = path

    def publish(self, run_id: int, line: str) -> None:
        line = line.rstrip("\n")
        with self._lock:
            self._history[run_id].append(line)
            if (f := self._files.get(run_id)) is not None:
                with f.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            subs = list(self._subs.get(run_id, []))
        for q in subs:
            self._put(q, line)

    def close(self, run_id: int) -> None:
        with self._lock:
            subs = list(self._subs.get(run_id, []))
            self._history[run_id].append(DONE)
        for q in subs:
            self._put(q, DONE)

    def _put(self, q: asyncio.Queue[str], item: str) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(q.put_nowait, item)
        else:
            q.put_nowait(item)

    async def subscribe(self, run_id: int, logs_path: Path | None = None) -> AsyncIterator[str]:
        q: asyncio.Queue[str] = asyncio.Queue()
        with self._lock:
            history = list(self._history.get(run_id, []))
            if not history and logs_path and logs_path.exists():
                history = logs_path.read_text(encoding="utf-8").splitlines() + [DONE]
            self._subs[run_id].append(q)
        try:
            for line in history:
                if line == DONE:
                    return
                yield line
            while True:
                line = await q.get()
                if line == DONE:
                    return
                yield line
        finally:
            with self._lock:
                self._subs[run_id].remove(q)


class JobRunner:
    """Runs blocking orchestrator functions in worker threads so the API stays responsive.
    Callable from sync or async code. Single user → a small pool is enough."""

    def __init__(self, workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
        def _run() -> Any:
            try:
                return fn(*args)
            except Exception:  # orchestrator records failures itself; this is a last resort
                log.exception("background job %s failed", getattr(fn, "__name__", fn))

        return self._pool.submit(_run)


log_bus = LogBus()
jobs = JobRunner()
