"""Docker sandbox hardening (PLAN.md §5, §12): malicious code must fail safely.

Skipped automatically when no Docker daemon is reachable (see conftest.py). The first run
builds the analysis-runner image, which takes several minutes.
"""
import pandas as pd
import pytest

from app.sandbox.manager import ensure_image, run_in_sandbox

pytestmark = pytest.mark.docker

RESULTS = '''
import json, os

def _ok(output_dir, title):
    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump({"summary": {"title": title, "rows_processed": 0}}, f)
'''

NETWORK = RESULTS + '''
import socket

def run(input_dir, output_dir, params):
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3)
        title = "network reachable"
    except OSError as exc:
        title = "blocked: " + type(exc).__name__
    _ok(output_dir, title)
'''

WRITES = RESULTS + '''
def run(input_dir, output_dir, params):
    blocked = []
    for path in ("/etc/pwned", "/input/pwned", "/code/pwned", "/opt/runner/pwned", "/pwned"):
        try:
            open(path, "w").write("x")
        except OSError:
            blocked.append(path)
    open("/tmp/scratch", "w").write("tmp is fine")
    _ok(output_dir, ",".join(blocked))
'''

FORK_BOMB = RESULTS + '''
import os, time

def run(input_dir, output_dir, params):
    pids, errors = [], 0
    for _ in range(2000):
        try:
            pid = os.fork()
        except OSError:
            errors += 1
            break
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        pids.append(pid)
    _ok(output_dir, f"forked={len(pids)} limited={errors > 0}")
    for pid in pids:
        os.kill(pid, 9)
'''

SLOW = '''
import time

def run(input_dir, output_dir, params):
    print("sleeping", flush=True)
    time.sleep(120)
'''


@pytest.fixture(scope="module", autouse=True)
def image():
    ensure_image()


@pytest.fixture
def input_dir(tmp_path):
    d = tmp_path / "input"
    d.mkdir()
    pd.DataFrame({"a": [1, 2]}).to_parquet(d / "data.parquet")
    return d


def run(code, input_dir, out, **kw):
    return run_in_sandbox(code, "run", input_dir, out, {}, backend="docker", skip_static_check=True, **kw)


def test_network_blocked(input_dir, tmp_path):
    res = run(NETWORK, input_dir, tmp_path / "out")
    assert res.ok, res.error
    assert res.results["summary"]["title"].startswith("blocked")


def test_writes_outside_output_fail(input_dir, tmp_path):
    res = run(WRITES, input_dir, tmp_path / "out")
    assert res.ok, res.error
    blocked = res.results["summary"]["title"].split(",")
    assert set(blocked) == {"/etc/pwned", "/input/pwned", "/code/pwned", "/opt/runner/pwned", "/pwned"}
    assert not (input_dir / "pwned").exists()


def test_fork_bomb_contained(input_dir, tmp_path):
    res = run(FORK_BOMB, input_dir, tmp_path / "out", timeout_s=120)
    assert res.ok, res.error
    title = res.results["summary"]["title"]
    assert "limited=True" in title
    assert int(title.split()[0].split("=")[1]) < 300  # sandbox_pids_limit = 256


def test_timeout_kills_container(input_dir, tmp_path):
    lines: list[str] = []
    res = run(SLOW, input_dir, tmp_path / "out", timeout_s=5, on_log=lines.append)
    assert not res.ok and res.error == "timeout" and res.duration_s < 60
    assert "sleeping" in lines
