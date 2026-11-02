"""Stage 2: dataset profiles, validation, data contracts, drift (PLAN.md §2, §3, §6)."""
from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    name: str
    inferred_type: str  # integer | float | string | category | boolean | date | datetime
    null_pct: float
    unique_count: int
    min: Any = None
    max: Any = None
    mean: float | None = None
    std: float | None = None
    top_values: list[tuple[str, int]] = Field(default_factory=list)  # up to 10
    sample_values: list[str] = Field(default_factory=list)  # up to 5


class DatasetProfile(BaseModel):
    dataset_id: int
    file_name: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)  # <= settings.llm_sample_rows


ValidationStatus = Literal["ready", "needs_more_data", "ready_with_warnings"]


class ColumnMapping(BaseModel):
    spec_column: str
    dataset_id: int
    source_column: str
    transform: str = Field(default="", description="Optional note, e.g. 'parse as date dd/mm/yyyy'")


class Gap(BaseModel):
    severity: Literal["blocker", "warning", "info"]
    kind: str  # missing_column | wrong_type | too_many_nulls | too_few_rows | short_date_range | leakage_risk | join_issue | other
    column: str | None = None
    message: str
    suggestion: str = ""


class JoinSpec(BaseModel):
    left_dataset_id: int
    right_dataset_id: int
    left_key: str
    right_key: str
    how: Literal["inner", "left", "outer"] = "left"
    match_rate: float | None = None


class ValidationReport(BaseModel):
    status: ValidationStatus
    mapping: list[ColumnMapping]
    gaps: list[Gap] = Field(default_factory=list)
    joins: list[JoinSpec] = Field(default_factory=list)
    summary: str = ""


class ContractColumn(BaseModel):
    name: str  # canonical (spec) name after mapping
    source_column: str
    dataset_index: int  # position of the file in the upload list (files are matched by order / name)
    type: str
    nullable_pct: float  # null % seen at freeze time
    min: float | None = None
    max: float | None = None
    categories: list[str] | None = None  # for low-cardinality string columns
    # False for extra columns passed through unmapped: missing on a re-run is a warning, not an error.
    required: bool = True


class DataContract(BaseModel):
    """Frozen schema after the first successful run. Every future upload is checked against it."""
    files: list[str]  # original file names in order
    columns: list[ContractColumn]
    joins: list[JoinSpec] = Field(default_factory=list)
    min_rows: int = 1


class ContractIssue(BaseModel):
    severity: Literal["error", "warning"]
    column: str | None = None
    kind: str  # missing_column | type_mismatch | new_categories | null_spike | out_of_range | too_few_rows | file_count
    message: str


class ContractCheckResult(BaseModel):
    ok: bool
    issues: list[ContractIssue] = Field(default_factory=list)
    suggested_mapping: dict[str, str] = Field(default_factory=dict)  # contract source col -> new col


class DriftColumn(BaseModel):
    column: str
    method: Literal["psi", "ks"]
    statistic: float
    p_value: float | None = None
    drifted: bool


class DriftReport(BaseModel):
    drifted: bool
    columns: list[DriftColumn] = Field(default_factory=list)
