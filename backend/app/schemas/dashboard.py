"""Dashboard Spec (PLAN.md §3 Stage 5). The LLM only picks widgets and binds them
to results.json keys; the frontend renders with a fixed component set.

Keep in sync with frontend/lib/types.ts.
"""
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.results import Format

WidgetType = Literal[
    "kpi", "line", "bar", "scatter", "histogram", "heatmap", "pie", "table",
    "feature_importance", "confusion_matrix", "forecast_with_interval", "text_insight",
]

GRID_COLUMNS = 12


class Layout(BaseModel):
    x: int = Field(ge=0, lt=GRID_COLUMNS)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=GRID_COLUMNS)
    h: int = Field(ge=1, description="Grid rows; one row is ~80px")


class Binding(BaseModel):
    """Where the widget's data comes from in results.json.

    source: "kpis" | "series" | "tables" | "model" | "stat_tests" | "insights"
    keys:   item keys within that source (several series keys = multi-series chart)
    """
    source: Literal["kpis", "series", "tables", "model", "stat_tests", "insights"]
    keys: list[str] = Field(default_factory=list)
    x_column: str | None = None  # for tables-backed charts
    y_columns: list[str] = Field(default_factory=list)
    top_n: int | None = None  # keep top N, group rest as "Other"


class Widget(BaseModel):
    id: str
    type: WidgetType
    title: str
    subtitle: str | None = None
    binding: Binding
    layout: Layout
    tab: str = "Overview"
    x_label: str | None = None
    y_label: str | None = None
    format: Format | None = None
    orientation: Literal["vertical", "horizontal"] = "vertical"
    stacked: bool = False
    hidden_columns: list[str] = Field(default_factory=list)  # tables > 8 cols: behind column picker
    text: str | None = None  # text_insight body (markdown)


class Filter(BaseModel):
    id: str
    label: str
    table_key: str
    column: str


class DashboardSpec(BaseModel):
    title: str
    tabs: list[str] = Field(default_factory=lambda: ["Overview"])
    widgets: list[Widget]
    filters: list[Filter] = Field(default_factory=list)
