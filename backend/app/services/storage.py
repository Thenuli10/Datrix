"""On-disk layout (PLAN.md §6): storage/projects/{pid}/{uploads,pipelines/v{n},runs/{run_id}}."""
from pathlib import Path

from app.core.config import settings


def _mk(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_dir(pid: int) -> Path:
    """storage/projects/{pid}/"""
    return _mk(settings.project_dir(pid))


def upload_path(pid: int, dataset_id: int, ext: str) -> Path:
    """storage/projects/{pid}/uploads/{dataset_id}.{ext} (parent dir created)."""
    return _mk(project_dir(pid) / "uploads") / f"{dataset_id}.{ext.lstrip('.').lower()}"


def pipeline_dir(pid: int, version: int) -> Path:
    """storage/projects/{pid}/pipelines/v{version}/"""
    return _mk(project_dir(pid) / "pipelines" / f"v{version}")


def run_dir(pid: int, run_id: int) -> Path:
    """storage/projects/{pid}/runs/{run_id}/ (with an artifacts/ subdir)."""
    path = _mk(project_dir(pid) / "runs" / str(run_id))
    _mk(path / "artifacts")
    return path
