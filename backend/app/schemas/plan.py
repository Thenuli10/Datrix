"""Stage 3: Strategy Planner output (PLAN.md §3)."""
from typing import Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    title: str
    detail: str


class MLSpec(BaseModel):
    problem: Literal["classification", "regression", "forecasting", "clustering"]
    target: str | None = None
    features: list[str] = Field(default_factory=list)
    excluded_columns: list[str] = Field(default_factory=list, description="Dropped for leakage / IDs")
    model_family: str  # e.g. "lightgbm", "xgboost", "random_forest", "kmeans", "statsmodels_sarimax"
    validation: str  # e.g. "time-based split: last 20% of dates as test"
    metrics: list[str]
    baseline: str = Field(description="Simple baseline to beat, e.g. majority class / mean / last value")
    time_column: str | None = None
    horizon: int | None = None


class AnalysisPlan(BaseModel):
    path: Literal["ml", "script"]
    title: str
    rationale: str
    steps: list[PlanStep]
    ml: MLSpec | None = None
    expected_outputs: list[str] = Field(description="results.json keys / items the code will produce")
    assumptions: list[str] = Field(default_factory=list)
