/**
 * TypeScript mirrors of the backend contracts.
 * Keep in sync with backend/app/schemas/*.py and backend/app/models/tables.py.
 * (Optionally generated types live in lib/openapi.d.ts via `npm run gen:api`;
 * these handwritten ones are the source of truth used in code.)
 */

/* ------------------------------------------------------------------ */
/* Enums (models/tables.py)                                            */
/* ------------------------------------------------------------------ */

export const PROJECT_STATUSES = [
  "DRAFT",
  "REQUIREMENTS_READY",
  "DATA_UPLOADED",
  "DATA_VALIDATED",
  "PLAN_PROPOSED",
  "PLAN_APPROVED",
  "RUNNING",
  "COMPLETED",
  "FAILED",
  "RERUNNING",
] as const;
export type ProjectStatus = (typeof PROJECT_STATUSES)[number];

export const RUN_STATUSES = ["QUEUED", "RUNNING", "CHECKING", "COMPLETED", "FAILED"] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

/* ------------------------------------------------------------------ */
/* schemas/requirement.py                                              */
/* ------------------------------------------------------------------ */

export type TaskType =
  | "prediction"
  | "classification"
  | "forecasting"
  | "clustering"
  | "descriptive"
  | "statistical_test"
  | "other";

export type ColumnType = "integer" | "float" | "string" | "category" | "boolean" | "date" | "datetime";

export interface SpecColumn {
  name: string;
  type: ColumnType;
  description: string;
  example_values: string[];
  required: boolean;
}

export interface DataSpec {
  granularity: string;
  columns: SpecColumn[];
  min_rows: number;
  min_date_range_days: number | null;
  notes: string;
  multiple_files_hint: string;
}

export interface RequirementAnalysis {
  task_type: TaskType;
  summary: string;
  clarifying_questions: string[];
  data_spec: DataSpec;
  success_criteria: string[];
  ready: boolean;
}

/* ------------------------------------------------------------------ */
/* schemas/data.py                                                     */
/* ------------------------------------------------------------------ */

export interface ColumnProfile {
  name: string;
  inferred_type: string; // integer | float | string | category | boolean | date | datetime
  null_pct: number; // 0–100
  unique_count: number;
  min: unknown;
  max: unknown;
  mean: number | null;
  std: number | null;
  top_values: [string, number][];
  sample_values: string[];
}

export interface DatasetProfile {
  dataset_id: number;
  file_name: string;
  row_count: number;
  column_count: number;
  columns: ColumnProfile[];
  sample_rows: Record<string, unknown>[];
}

export type ValidationStatus = "ready" | "needs_more_data" | "ready_with_warnings";

export interface ColumnMapping {
  spec_column: string;
  dataset_id: number;
  source_column: string;
  transform: string;
}

export type GapSeverity = "blocker" | "warning" | "info";

export interface Gap {
  severity: GapSeverity;
  kind: string; // missing_column | wrong_type | too_many_nulls | too_few_rows | short_date_range | leakage_risk | join_issue | other
  column: string | null;
  message: string;
  suggestion: string;
}

export interface JoinSpec {
  left_dataset_id: number;
  right_dataset_id: number;
  left_key: string;
  right_key: string;
  how: "inner" | "left" | "outer";
  match_rate: number | null;
}

export interface ValidationReport {
  status: ValidationStatus;
  mapping: ColumnMapping[];
  gaps: Gap[];
  joins: JoinSpec[];
  summary: string;
}

export interface ContractColumn {
  name: string;
  source_column: string;
  dataset_index: number;
  type: string;
  nullable_pct: number;
  min: number | null;
  max: number | null;
  categories: string[] | null;
}

export interface DataContract {
  files: string[];
  columns: ContractColumn[];
  joins: JoinSpec[];
  min_rows: number;
}

export interface ContractIssue {
  severity: "error" | "warning";
  column: string | null;
  kind: string; // missing_column | type_mismatch | new_categories | null_spike | out_of_range | too_few_rows | file_count
  message: string;
}

export interface ContractCheckResult {
  ok: boolean;
  issues: ContractIssue[];
  suggested_mapping: Record<string, string>;
}

/**
 * Run.contract_check_json as stored by the orchestrator: a ContractCheckResult merged with the
 * re-run options. Before the check has run it only contains `data_mode` / `mapping_override`.
 */
export type StoredContractCheck = Partial<ContractCheckResult> & {
  data_mode?: DataMode;
  mapping_override?: Record<string, string> | null;
};

export interface DriftColumn {
  column: string;
  method: "psi" | "ks";
  statistic: number;
  p_value: number | null;
  drifted: boolean;
}

export interface DriftReport {
  drifted: boolean;
  columns: DriftColumn[];
}

/* ------------------------------------------------------------------ */
/* schemas/plan.py                                                     */
/* ------------------------------------------------------------------ */

export interface PlanStep {
  title: string;
  detail: string;
}

export type MLProblem = "classification" | "regression" | "forecasting" | "clustering";

export interface MLSpec {
  problem: MLProblem;
  target: string | null;
  features: string[];
  excluded_columns: string[];
  model_family: string;
  validation: string;
  metrics: string[];
  baseline: string;
  time_column: string | null;
  horizon: number | null;
}

export type PlanPath = "ml" | "script";

export interface AnalysisPlan {
  path: PlanPath;
  title: string;
  rationale: string;
  steps: PlanStep[];
  ml: MLSpec | null;
  expected_outputs: string[];
  assumptions: string[];
}

/* ------------------------------------------------------------------ */
/* schemas/results.py                                                  */
/* ------------------------------------------------------------------ */

export type Format = "number" | "percent" | "currency" | "compact" | "integer" | "text" | "date";

export interface Summary {
  title: string;
  rows_processed: number;
  rows_dropped: number;
  drop_reasons: string[];
  input_date_min: string | null;
  input_date_max: string | null;
  [extra: string]: unknown;
}

export interface KPI {
  key: string;
  label: string;
  value: number | string | null;
  format: Format;
  unit: string | null;
  description: string | null;
}

export interface Series {
  key: string;
  label: string | null;
  x: unknown[];
  y: (number | null)[];
  x_label: string | null;
  y_label: string | null;
  group: string | null;
  kind: "line" | "bar" | "scatter" | "area" | null;
  y_lower: (number | null)[] | null;
  y_upper: (number | null)[] | null;
  is_forecast: boolean;
  format: Format;
}

export interface Table {
  key: string;
  label: string | null;
  columns: string[];
  rows: unknown[][];
  column_formats: Record<string, Format>;
}

export interface FeatureImportance {
  feature: string;
  importance: number;
}

export interface ModelInfo {
  type: string;
  metrics: Record<string, number>;
  baseline_metrics: Record<string, number>;
  feature_importance: FeatureImportance[];
  confusion_matrix: number[][] | null;
  class_labels: string[] | null;
  target: string | null;
  [extra: string]: unknown;
}

export interface StatTest {
  key: string;
  test: string;
  statistic: number | null;
  p_value: number | null;
  n: number;
  conclusion: string;
}

export interface Results {
  summary: Summary;
  kpis: KPI[];
  series: Series[];
  tables: Table[];
  model: ModelInfo | null;
  stat_tests: StatTest[];
  insights_raw: string[];
}

/* ------------------------------------------------------------------ */
/* schemas/checks.py                                                   */
/* ------------------------------------------------------------------ */

export type Severity = "high" | "medium" | "low";
export type CheckStatus = "pass" | "warn" | "fail";

export interface SanityIssue {
  severity: Severity;
  check: string;
  message: string;
  suggested_fix: string;
  layer: 1 | 2 | 3 | 4;
}

export interface SanityReport {
  status: CheckStatus;
  issues: SanityIssue[];
  checks_run: number;
  checks_passed: number;
}

export interface SpotCheck {
  name: string;
  results_ref: string;
  expected: number;
  actual: number | null;
  tolerance: number;
}

export interface DashboardIssue {
  severity: Severity;
  widget_id: string | null;
  rule: string;
  message: string;
  auto_fixed: boolean;
}

export interface DashboardQAReport {
  status: CheckStatus;
  issues: DashboardIssue[];
  rounds: number;
  screenshots: string[];
}

/* ------------------------------------------------------------------ */
/* schemas/dashboard.py                                                */
/* ------------------------------------------------------------------ */

export const WIDGET_TYPES = [
  "kpi",
  "line",
  "bar",
  "scatter",
  "histogram",
  "heatmap",
  "pie",
  "table",
  "feature_importance",
  "confusion_matrix",
  "forecast_with_interval",
  "text_insight",
] as const;
export type WidgetType = (typeof WIDGET_TYPES)[number];

export const GRID_COLUMNS = 12;
export const GRID_ROW_PX = 80;

export interface Layout {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type BindingSource = "kpis" | "series" | "tables" | "model" | "stat_tests" | "insights";

export interface Binding {
  source: BindingSource;
  keys: string[];
  x_column: string | null;
  y_columns: string[];
  top_n: number | null;
}

export interface Widget {
  id: string;
  type: WidgetType;
  title: string;
  subtitle: string | null;
  binding: Binding;
  layout: Layout;
  tab: string;
  x_label: string | null;
  y_label: string | null;
  format: Format | null;
  orientation: "vertical" | "horizontal";
  stacked: boolean;
  hidden_columns: string[];
  text: string | null;
}

export interface Filter {
  id: string;
  label: string;
  table_key: string;
  column: string;
}

export interface DashboardSpec {
  title: string;
  tabs: string[];
  widgets: Widget[];
  filters: Filter[];
}

/* ------------------------------------------------------------------ */
/* API entities (tables.py rows, serialized with model_dump(mode="json")) */
/* ------------------------------------------------------------------ */

export interface Message {
  id: number;
  project_id: number;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
}

/** Response of GET /projects, GET /projects/{id}, POST /projects, POST /projects/{id}/messages. */
export interface Project {
  id: number;
  name: string;
  status: ProjectStatus;
  requirement_text: string;
  context_json: ProjectContext;
  analysis_json: RequirementAnalysis | null;
  thumbnail_path: string | null;
  created_at: string;
  // detail extras
  analysis: RequirementAnalysis | null;
  messages: Message[];
  latest_run_id: number | null;
  latest_run_status: RunStatus | null;
  pipeline_id: number | null;
}

export interface ProjectContext {
  domain?: string;
  goal?: string;
  time_horizon?: string;
  [k: string]: unknown;
}

export interface ProjectCreate {
  requirement: string;
  name?: string;
  context: ProjectContext;
}

export type DatasetPurpose = "initial" | "rerun";

export interface Dataset {
  id: number;
  project_id: number;
  original_name: string;
  file_path: string;
  file_type: string; // csv | xlsx | parquet | json
  purpose: DatasetPurpose;
  profile_json: DatasetProfile | null;
  uploaded_at: string;
}

export interface Validation {
  id: number;
  project_id: number;
  dataset_ids: number[];
  status: ValidationStatus;
  gap_report_json: ValidationReport;
  column_mapping_json: ColumnMapping[];
  created_at: string;
}

export interface Plan {
  id: number;
  project_id: number;
  path: PlanPath;
  plan_json: AnalysisPlan;
  approved: boolean;
  created_at: string;
}

export type RunMode = "train" | "predict" | "script";

export interface Run {
  id: number;
  project_id: number;
  pipeline_id: number | null;
  dataset_ids: number[];
  mode: RunMode;
  status: RunStatus;
  stage: string;
  error: string | null;
  logs_path: string | null;
  results_path: string | null;
  metrics_json: Record<string, unknown> | null;
  sanity_json: SanityReport | null;
  dashboard_qa_json: DashboardQAReport | null;
  contract_check_json: StoredContractCheck | null;
  drift_json: DriftReport | null;
  insights_md: string | null;
  thumbnail_path: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/** GET /pipelines/{id}/runs items. */
export interface RunWithKpis extends Run {
  kpis: KPI[];
}

export interface Pipeline {
  id: number;
  project_id: number;
  version: number;
  path: PlanPath;
  code_path: string | null;
  spot_check_path: string | null;
  model_path: string | null;
  contract_json: DataContract | null;
  dashboard_spec_json: DashboardSpec | null;
  active: boolean;
  created_at: string;
  // summary extras
  project_name: string;
  run_count: number;
}

export interface PipelineCode {
  code: string | null;
  spot_check: string | null;
}

/** GET /runs/{id}/dashboard */
export interface DashboardPayload {
  run: Run;
  spec: DashboardSpec | null;
  results: Results | null;
  sanity: SanityReport | null;
  dashboard_qa: DashboardQAReport | null;
  insights_md: string | null;
  contract_check: StoredContractCheck | null;
  drift: DriftReport | null;
}

export type RerunMode = "predict" | "retrain" | "script";
export type DataMode = "replace" | "append";
