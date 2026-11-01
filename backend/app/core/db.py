"""SQLite engine and session helpers."""
from collections.abc import Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

settings.storage_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.db_url, connect_args={"check_same_thread": False})


def init_db() -> None:
    from app.models import tables  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all never alters existing tables: add columns introduced after a DB was created."""
    added = {"llm_calls": {"run_id": "INTEGER"}}
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in added.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, sql_type in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{name} ON {table} ({name})"))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
