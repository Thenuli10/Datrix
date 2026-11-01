"""results.json contract (PLAN.md §7). All generated code must emit this shape.

Keep in sync with sandbox-image/runner.py (which does a lightweight structural check
inside the container) and frontend/lib/types.ts.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Format = Literal["number", "percent", "currency", "compact", "integer", "text", "date"]


class Summary(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str
    rows_processed: int
    rows_dropped: int = 0
    drop_reasons: list[str] = Field(default_factory=list)
    input_date_min: str | None = None
    input_date_max: str | None = None


class KPI(BaseModel):
    key: str
    label: str
    value: float | int | str | None
    format: Format = "number"
    unit: str | None = None
    description: str | None = None


class Series(BaseModel):
    key: str
    label: str | None = None
    x: list[Any]
    y: list[float | int | None]
    x_label: str | None = None
    y_label: str | None = None
    group: str | None = Field(default=None, description="Series sharing a group are drawn together")
    kind: Literal["line", "bar", "scatter", "area"] | None = None
    y_lower: list[float | None] | None = None  # forecast intervals
    y_upper: list[float | None] | None = None
    is_forecast: bool = False
    format: Format = "number"


class Table(BaseModel):
    key: str
    label: str | None = None
    columns: list[str]
    rows: list[list[Any]]
    column_formats: dict[str, Format] = Field(default_factory=dict)


class FeatureImportance(BaseModel):
    feature: str
    importance: float


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())
    type: str
    metrics: dict[str, float]
    baseline_metrics: dict[str, float] = Field(default_factory=dict)
    feature_importance: list[FeatureImportance] = Field(default_factory=list)
    confusion_matrix: list[list[int]] | None = None
    class_labels: list[str] | None = None
    target: str | None = None


class StatTest(BaseModel):
    key: str
    test: str
    statistic: float | None
    p_value: float | None
    n: int
    conclusion: str


class Results(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    summary: Summary
    kpis: list[KPI] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    model: ModelInfo | None = None
    stat_tests: list[StatTest] = Field(default_factory=list)
    insights_raw: list[str] = Field(default_factory=list)

    def keys(self) -> set[str]:
        return {*(k.key for k in self.kpis), *(s.key for s in self.series),
                *(t.key for t in self.tables), *(s.key for s in self.stat_tests)}
