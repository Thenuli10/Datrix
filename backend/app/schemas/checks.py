"""Results Sanity Checker (§7a) and Dashboard QA (§7b) reports."""
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["high", "medium", "low"]


class SanityIssue(BaseModel):
    severity: Severity
    check: str  # row_accounting | bad_numbers | range | date_coverage | target_leakage | below_baseline | stat_test | spot_check | plan_mismatch | unsupported_insight | implausible | kpi_jump | metric_drop | structure_changed
    message: str
    suggested_fix: str = ""
    layer: Literal[1, 2, 3, 4] = 1  # 4 = comparison with past runs


class SanityReport(BaseModel):
    status: Literal["pass", "warn", "fail"]
    issues: list[SanityIssue] = Field(default_factory=list)
    checks_run: int = 0
    checks_passed: int = 0


class SpotCheck(BaseModel):
    """One Layer-2 recalculation, produced by running the saved spot-check script."""
    name: str
    results_ref: str  # e.g. "kpis.total_revenue" or "summary.rows_processed"
    expected: float  # recomputed from raw data
    actual: float | None = None  # read from results.json
    tolerance: float = 0.01  # relative


class DashboardIssue(BaseModel):
    severity: Severity
    widget_id: str | None = None
    rule: str  # overlap | gap | too_many_series | pie_slices | long_labels | missing_title | missing_axis | unformatted | empty | wide_table | above_fold | overflow | cutoff | small_text | contrast | vision
    message: str
    auto_fixed: bool = False


class DashboardQAReport(BaseModel):
    status: Literal["pass", "warn", "fail"]
    issues: list[DashboardIssue] = Field(default_factory=list)
    rounds: int = 0
    screenshots: list[str] = Field(default_factory=list)  # storage-relative paths
