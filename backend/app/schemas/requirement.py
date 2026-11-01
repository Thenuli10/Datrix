"""Stage 1: Requirement Analyst output (PLAN.md §3, §9)."""
from typing import Literal

from pydantic import BaseModel, Field

TaskType = Literal[
    "prediction", "classification", "forecasting", "clustering",
    "descriptive", "statistical_test", "other",
]
ColumnType = Literal["integer", "float", "string", "category", "boolean", "date", "datetime"]


class SpecColumn(BaseModel):
    name: str = Field(description="snake_case canonical column name")
    type: ColumnType
    description: str
    example_values: list[str] = Field(default_factory=list)
    required: bool = True


class DataSpec(BaseModel):
    granularity: str = Field(description="What one row represents, e.g. 'one customer per month'")
    columns: list[SpecColumn]
    min_rows: int = 50
    min_date_range_days: int | None = None
    notes: str = ""
    multiple_files_hint: str = Field(
        default="", description="If data usually lives in several tables, how they join"
    )


class RequirementAnalysis(BaseModel):
    task_type: TaskType
    summary: str = Field(description="One-sentence restatement of the user's goal")
    clarifying_questions: list[str] = Field(default_factory=list)
    data_spec: DataSpec
    success_criteria: list[str]
    ready: bool = Field(description="True when no clarifying questions remain")
