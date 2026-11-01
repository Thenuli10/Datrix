"""Application settings, loaded from environment / backend/.env."""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # LLM
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    openai_small_model: str = "gpt-4.1-mini"
    openai_vision_model: str = "gpt-4.1"
    llm_sample_rows: int = 20  # max sample rows ever sent to the LLM (privacy, §9)
    llm_fake: bool = False  # use FakeLLMClient (tests / offline)

    # Storage
    storage_dir: Path = REPO_DIR / "storage"
    database_url: str = ""  # defaults to sqlite in storage_dir
    max_upload_mb: int = 200

    # Sandbox
    sandbox_image: str = "analysis-runner:py3.12"
    sandbox_backend: str = "docker"  # "docker" | "local" (local subprocess, dev only)
    sandbox_memory: str = "2g"
    sandbox_cpus: float = 2.0
    sandbox_pids_limit: int = 256
    sandbox_timeout_s: int = 600

    # Loops
    max_fix_attempts: int = 4
    max_sanity_rounds: int = 2
    max_dashboard_qa_rounds: int = 2

    # Frontend (for Playwright screenshots)
    frontend_url: str = "http://localhost:3000"
    screenshots_enabled: bool = True

    # Sanity thresholds (configurable, §13)
    sanity_max_silent_drop: float = 0.20
    sanity_leak_auc: float = 0.98
    sanity_leak_r2: float = 0.99
    compare_kpi_jump: float = 0.50
    compare_metric_drop: float = 0.05

    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("storage_dir")
    @classmethod
    def _absolute(cls, v: Path) -> Path:
        # Stored file paths and Docker bind mounts need absolute paths.
        return v.expanduser().resolve()

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.storage_dir / 'datrix.db').as_posix()}"

    def project_dir(self, project_id: int) -> Path:
        return self.storage_dir / "projects" / str(project_id)


settings = Settings()
