"""LLM spend overview: today's cost, per-project totals, configured caps (settings.llm_*)."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.db import get_session
from app.llm.budget import usage_summary

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
def get_usage(session: Session = Depends(get_session)) -> dict[str, Any]:
    return usage_summary(session)
