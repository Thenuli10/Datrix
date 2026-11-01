"""Shared API helpers."""
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlmodel import Session

T = TypeVar("T")


def get_or_404(session: Session, model: type[T], id_: int) -> T:
    obj = session.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


def dump(obj: Any) -> Any:
    return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj
