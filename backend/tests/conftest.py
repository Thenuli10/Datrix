"""Shared test setup. Env vars are set before any app module is imported (settings read env at import)."""
import atexit
import os
import shutil
import tempfile

import pytest

_STORAGE = tempfile.mkdtemp(prefix="datrix_test_")
os.environ["LLM_FAKE"] = "true"
os.environ["STORAGE_DIR"] = _STORAGE
atexit.register(shutil.rmtree, _STORAGE, True)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "docker: needs a running Docker daemon (skipped otherwise)")


def _docker_up() -> bool:
    try:
        import docker

        return bool(docker.from_env(timeout=3).ping())
    except Exception:  # noqa: BLE001
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    docker_items = [i for i in items if "docker" in i.keywords]
    if docker_items and not _docker_up():
        skip = pytest.mark.skip(reason="Docker daemon not reachable")
        for item in docker_items:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def _init_db() -> None:
    """Tables must exist: OpenAIClient checks spend caps against llm_calls before every request."""
    from app.core.db import init_db

    init_db()
