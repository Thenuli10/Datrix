"""Sandbox manager: run generated code in a hardened Docker container (PLAN.md §5).

`settings.sandbox_backend == "local"` runs the same runner.py in a subprocess instead
(dev only, NO isolation).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.config import REPO_DIR, settings
from app.sandbox.static_check import check_code

Entry = Literal["run", "train", "predict", "spot_check"]
LogFn = Callable[[str], None]

IMAGE_DIR = REPO_DIR / "sandbox-image"
RUNNER_PATH = IMAGE_DIR / "runner.py"
CONTAINER_RUNNER = "/opt/runner/runner.py"
ERROR_PREFIX = "::error::"
SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "OPENAI", "DATABASE_URL")


@dataclass
class SandboxResult:
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    results: dict[str, Any] | None
    error: str | None
    duration_s: float


# ---------------------------------------------------------------- helpers

def _noop(_: str) -> None:
    pass


def _parse_error(stdout: str, stderr: str) -> str | None:
    """Last `::error::` line from the runner, if any."""
    for line in reversed((stdout + "\n" + stderr).splitlines()):
        if line.startswith(ERROR_PREFIX):
            return line[len(ERROR_PREFIX):].strip()
    return None


def _prepare_code_dir(code: str, params: dict[str, Any]) -> Path:
    """Per-run temp dir holding code.py + params.json (mounted read-only at /code)."""
    root = settings.storage_dir / "sandbox_tmp"
    root.mkdir(parents=True, exist_ok=True)
    code_dir = Path(tempfile.mkdtemp(prefix="run_", dir=root))
    (code_dir / "code.py").write_text(code, encoding="utf-8")
    (code_dir / "params.json").write_text(json.dumps(params, default=str), encoding="utf-8")
    return code_dir


def _finish(entry: Entry, output_dir: Path, exit_code: int | None, stdout: str, stderr: str,
            error: str | None, started: float) -> SandboxResult:
    """Build the result; read results.json when the runner succeeded."""
    results: dict[str, Any] | None = None
    if error is None and exit_code != 0:
        error = _parse_error(stdout, stderr) or f"exit code {exit_code}: {stderr.strip()[-500:]}"
    if error is None and entry != "spot_check":
        try:
            results = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            error = f"could not read results.json: {exc}"
    return SandboxResult(ok=error is None, exit_code=exit_code, stdout=stdout, stderr=stderr,
                         results=results, error=error, duration_s=round(time.monotonic() - started, 3))


def _pump(stream: Any, sink: list[str], on_log: LogFn) -> None:
    """Read text lines from a pipe into `sink`, forwarding each to on_log."""
    for line in iter(stream.readline, ""):
        line = line.rstrip("\r\n")
        sink.append(line)
        on_log(line)
    stream.close()


def _safe_env() -> dict[str, str]:
    """Process environment minus anything that looks like a secret."""
    env = {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in SECRET_MARKERS)}
    env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    return env


# ---------------------------------------------------------------- local backend

def _run_local(entry: Entry, code_dir: Path, input_dir: Path, output_dir: Path, model_dir: Path | None,
               on_log: LogFn, timeout_s: float) -> SandboxResult:
    started = time.monotonic()
    cmd = [sys.executable, "-u", "-X", "utf8", str(RUNNER_PATH), "--entry", entry,
           "--code", str(code_dir / "code.py"), "--input", str(input_dir), "--output", str(output_dir),
           "--params", str(code_dir / "params.json")]
    if model_dir is not None:
        cmd += ["--model", str(model_dir)]
    proc = subprocess.Popen(cmd, cwd=code_dir, env=_safe_env(), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    out: list[str] = []
    err: list[str] = []
    threads = [threading.Thread(target=_pump, args=(proc.stdout, out, on_log), daemon=True),
               threading.Thread(target=_pump, args=(proc.stderr, err, on_log), daemon=True)]
    for t in threads:
        t.start()
    error: str | None = None
    try:
        exit_code: int | None = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        exit_code = proc.wait()
        error = "timeout"
        on_log(f"::error::timeout after {timeout_s:g}s - process killed")
    for t in threads:
        t.join(timeout=5)
    return _finish(entry, output_dir, exit_code, "\n".join(out), "\n".join(err), error, started)


# ---------------------------------------------------------------- docker backend

def _docker_client(timeout: int = 60) -> Any:
    import docker  # imported lazily so the local backend works without a daemon

    return docker.from_env(timeout=timeout)


def docker_available() -> bool:
    """True when a Docker daemon answers a ping."""
    try:
        return bool(_docker_client(timeout=3).ping())
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False


def ensure_image(client: Any = None) -> str:
    """Build `settings.sandbox_image` from sandbox-image/ if it is not present. Returns the tag."""
    import docker.errors

    client = client or _docker_client(timeout=600)
    try:
        client.images.get(settings.sandbox_image)
    except docker.errors.ImageNotFound:
        client.images.build(path=str(IMAGE_DIR), tag=settings.sandbox_image, rm=True, pull=True)
    return settings.sandbox_image


def _bind(source: Path, target: str, read_only: bool) -> Any:
    from docker.types import Mount

    # Structured mounts avoid "C:\...:/input:ro" colon parsing; Docker Desktop accepts Windows paths.
    return Mount(target=target, source=str(source.resolve()), type="bind", read_only=read_only)


def _stream_docker(container: Any, stdout: bool, sink: list[str], on_log: LogFn) -> None:
    """Follow one container log stream, splitting chunks into lines."""
    buf = ""
    try:
        for chunk in container.logs(stream=True, follow=True, stdout=stdout, stderr=not stdout):
            buf += chunk.decode("utf-8", errors="replace")
            *lines, buf = buf.split("\n")
            for line in lines:
                sink.append(line.rstrip("\r"))
                on_log(line.rstrip("\r"))
    except Exception:  # noqa: BLE001 - stream ends when the container is killed/removed
        pass
    if buf:
        sink.append(buf)
        on_log(buf)


def _run_docker(entry: Entry, code_dir: Path, input_dir: Path, output_dir: Path, model_dir: Path | None,
                on_log: LogFn, timeout_s: float) -> SandboxResult:
    started = time.monotonic()
    client = _docker_client()
    ensure_image(client)
    if os.name == "posix":  # let uid 1000 write on Linux hosts
        for d in (output_dir, model_dir if entry == "train" else None):
            if d is not None:
                d.chmod(0o777)
    mounts = [_bind(input_dir, "/input", True), _bind(code_dir, "/code", True), _bind(output_dir, "/output", False)]
    cmd = ["--entry", entry, "--code", "/code/code.py", "--input", "/input", "--output", "/output",
           "--params", "/code/params.json"]
    if model_dir is not None:
        mounts.append(_bind(model_dir, "/model", entry != "train"))
        cmd += ["--model", "/model"]

    container = client.containers.create(
        settings.sandbox_image, command=cmd, mounts=mounts, detach=True,
        network_mode="none",
        mem_limit=settings.sandbox_memory, memswap_limit=settings.sandbox_memory,
        nano_cpus=int(settings.sandbox_cpus * 1e9), pids_limit=settings.sandbox_pids_limit,
        read_only=True, tmpfs={"/tmp": "rw,nosuid,nodev,size=512m,mode=1777"},
        user="1000:1000", security_opt=["no-new-privileges:true"], cap_drop=["ALL"],
        environment={"HOME": "/tmp", "MPLCONFIGDIR": "/tmp", "PYTHONUNBUFFERED": "1"},
        working_dir="/tmp", labels={"datrix.sandbox": "1"},
    )
    out: list[str] = []
    err: list[str] = []
    error: str | None = None
    exit_code: int | None = None
    try:
        container.start()
        threads = [threading.Thread(target=_stream_docker, args=(container, s, sink, on_log), daemon=True)
                   for s, sink in ((True, out), (False, err))]
        for t in threads:
            t.start()
        try:
            exit_code = int(container.wait(timeout=timeout_s).get("StatusCode", 1))
        except Exception:  # noqa: BLE001 - requests ReadTimeout / ConnectionError on timeout
            error = "timeout"
            on_log(f"::error::timeout after {timeout_s:g}s - container killed")
            try:
                container.kill()
            except Exception:  # noqa: BLE001 - already exited
                pass
        for t in threads:
            t.join(timeout=10)
        if exit_code == 137 and error is None:
            container.reload()
            if container.attrs.get("State", {}).get("OOMKilled"):
                error = f"out of memory (limit {settings.sandbox_memory})"
    finally:
        try:
            container.remove(force=True)
        except Exception:  # noqa: BLE001
            pass
    return _finish(entry, output_dir, exit_code, "\n".join(out), "\n".join(err), error, started)


# ---------------------------------------------------------------- public API

def run_in_sandbox(code: str, entry: Entry, input_dir: Path, output_dir: Path, params: dict[str, Any],
                   model_dir: Path | None = None, on_log: LogFn | None = None, timeout_s: float | None = None,
                   *, backend: str | None = None, skip_static_check: bool = False) -> SandboxResult:
    """Static-check `code`, then run `entry` in the sandbox and return its outcome.

    `backend` overrides settings.sandbox_backend ("docker" | "local"). `skip_static_check`
    exists for sandbox tests that must exercise the container's own defences.
    """
    on_log = on_log or _noop
    timeout_s = timeout_s or settings.sandbox_timeout_s
    started = time.monotonic()
    if not skip_static_check and (issues := check_code(code)):
        msg = "static check failed: " + "; ".join(issues)
        on_log(ERROR_PREFIX + msg)
        return SandboxResult(False, None, "", "", None, msg, 0.0)
    if entry in ("train", "predict") and model_dir is None:
        return SandboxResult(False, None, "", "", None, f"model_dir is required for entry '{entry}'", 0.0)

    input_dir, output_dir = Path(input_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if model_dir is not None:
        model_dir = Path(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
    code_dir = _prepare_code_dir(code, params)
    try:
        run = _run_local if (backend or settings.sandbox_backend) == "local" else _run_docker
        return run(entry, code_dir, input_dir, output_dir, model_dir, on_log, timeout_s)
    except Exception as exc:  # noqa: BLE001 - e.g. Docker daemon unreachable
        msg = f"sandbox error: {type(exc).__name__}: {exc}"
        on_log(ERROR_PREFIX + msg)
        return SandboxResult(False, None, "", "", None, msg, round(time.monotonic() - started, 3))
    finally:
        shutil.rmtree(code_dir, ignore_errors=True)


def run_spot_check(code: str, input_dir: Path, output_dir: Path, on_log: LogFn | None = None,
                   timeout_s: float | None = None, *, backend: str | None = None) -> dict[str, Any]:
    """Run a Layer-2 spot-check script (`def spot_check(input_dir) -> list[dict]`).

    Returns `{"ok": bool, "checks": list[dict], "error": str | None}`; the checks are the
    script's dicts (SpotCheck fields: name, results_ref, expected, tolerance).
    """
    res = run_in_sandbox(code, "spot_check", input_dir, output_dir, {}, None, on_log,
                         timeout_s or min(settings.sandbox_timeout_s, 120), backend=backend)
    checks: list[dict[str, Any]] = []
    error = res.error
    if res.ok:
        try:
            checks = json.loads((Path(output_dir) / "spot_check.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            error = f"could not read spot_check.json: {exc}"
    return {"ok": error is None, "checks": checks, "error": error}
