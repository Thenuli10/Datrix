/**
 * Realistic sample results.json + DashboardSpec covering every widget type.
 * Used by /dev/dashboard-preview to check the dashboard without a backend.
 */
import type { DashboardQAReport, DashboardSpec, Results, SanityReport } from "../types";

const months = [
  "2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01", "2024-06-01",
  "2024-07-01", "2024-08-01", "2024-09-01", "2024-10-01", "2024-11-01", "2024-12-01",
  "2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01", "2025-06-01",
];
const forecastMonths = ["2025-07-01", "2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01"];

const revenue = [182400, 176900, 191300, 198700, 205100, 212600, 208400, 219800, 226300, 241900, 263400, 289700,
  231200, 228900, 240300, 247800, 255600, 262100];
const forecast = [268900, 274300, 281200, 296700, 321500, 352800];
const churnRate = [0.061, 0.058, 0.064, 0.059, 0.055, 0.053, 0.057, 0.052, 0.049, 0.051, 0.047, 0.045,
  0.05, 0.048, 0.046, 0.044, 0.043, 0.041];

// deterministic pseudo-random
let seed = 42;
const rand = () => {
  seed = (seed * 16807) % 2147483647;
  return (seed - 1) / 2147483646;
};

const tenure = Array.from({ length: 220 }, () => Math.round(rand() * 60 + 1));
const monthlySpend = tenure.map((t) => Math.round((25 + t * 1.1 + rand() * 40) * 100) / 100);

const segments = [
  "Enterprise", "Mid-market", "SMB", "Startup", "Education", "Public sector", "Non-profit",
  "Healthcare & life sciences (regulated)", "Retail", "Other",
];

const customerRows: unknown[][] = Array.from({ length: 64 }, (_, i) => {
  const seg = segments[i % segments.length];
  const region = ["North America", "Europe", "APAC", "LATAM"][i % 4];
  const p = Math.round(rand() * 1000) / 1000;
  return [
    `CUST-${(1000 + i * 7).toString()}`,
    seg,
    region,
    tenure[i],
    monthlySpend[i],
    Math.round(rand() * 12),
    p,
    p > 0.5 ? "Yes" : "No",
    ["Monthly", "Annual", "Two-year"][i % 3],
    ["Card", "Invoice", "Bank transfer"][i % 3],
  ];
});

export const sampleResults: Results = {
  summary: {
    title: "Customer churn analysis — FY2024/25",
    rows_processed: 48213,
    rows_dropped: 312,
    drop_reasons: ["missing customer_id", "duplicate rows"],
    input_date_min: "2024-01-01",
    input_date_max: "2025-06-30",
  },
  kpis: [
    { key: "churn_rate", label: "Churn rate", value: 0.041, format: "percent", unit: null, description: "Last month, all segments" },
    { key: "total_revenue", label: "Revenue (18 mo.)", value: 4182300, format: "currency", unit: "USD", description: null },
    { key: "active_customers", label: "Active customers", value: 18452, format: "integer", unit: null, description: "+6.2% vs. last year" },
    { key: "avg_tenure", label: "Avg. tenure", value: 23.4, format: "number", unit: "months", description: null },
    { key: "arpu", label: "ARPU", value: 61.27, format: "currency", unit: "USD", description: null },
    { key: "events", label: "Events logged", value: 12873456, format: "compact", unit: null, description: null },
    { key: "last_refresh", label: "Data through", value: "2025-06-30", format: "date", unit: null, description: null },
  ],
  series: [
    { key: "monthly_revenue", label: "Revenue", x: months, y: revenue, x_label: "Month", y_label: "Revenue", group: "revenue", kind: "line", y_lower: null, y_upper: null, is_forecast: false, format: "currency" },
    {
      key: "revenue_forecast", label: "Forecast", x: forecastMonths, y: forecast, x_label: "Month", y_label: "Revenue", group: "revenue", kind: "line",
      y_lower: forecast.map((v, i) => Math.round(v * (0.94 - i * 0.012))), y_upper: forecast.map((v, i) => Math.round(v * (1.06 + i * 0.012))),
      is_forecast: true, format: "currency",
    },
    { key: "monthly_churn", label: "Churn rate", x: months, y: churnRate, x_label: "Month", y_label: "Churn rate", group: null, kind: "line", y_lower: null, y_upper: null, is_forecast: false, format: "percent" },
    { key: "new_customers", label: "New customers", x: months, y: [820, 790, 860, 910, 940, 980, 1010, 990, 1050, 1120, 1240, 1380, 1010, 980, 1060, 1110, 1150, 1190], x_label: "Month", y_label: "Customers", group: "acq", kind: "bar", y_lower: null, y_upper: null, is_forecast: false, format: "integer" },
    { key: "churned_customers", label: "Churned customers", x: months, y: [1120, 1060, 1170, 1090, 1010, 980, 1050, 960, 910, 950, 880, 850, 940, 910, 870, 840, 820, 790], x_label: "Month", y_label: "Customers", group: "acq", kind: "bar", y_lower: null, y_upper: null, is_forecast: false, format: "integer" },
    { key: "tenure_vs_spend", label: "Customers", x: tenure, y: monthlySpend, x_label: "Tenure (months)", y_label: "Monthly spend (USD)", group: null, kind: "scatter", y_lower: null, y_upper: null, is_forecast: false, format: "currency" },
    { key: "tenure_hist", label: "Customers", x: ["0–6", "6–12", "12–18", "18–24", "24–30", "30–36", "36–42", "42–48", "48–54", "54–60"], y: [3120, 2810, 2440, 2105, 1980, 1720, 1510, 1300, 1050, 917], x_label: "Tenure (months)", y_label: "Customers", group: null, kind: "bar", y_lower: null, y_upper: null, is_forecast: false, format: "integer" },
  ],
  tables: [
    {
      key: "churn_by_segment",
      label: "Churn by segment",
      columns: ["segment", "customers", "churn_rate", "revenue"],
      rows: segments.map((s, i) => [s, [5120, 3980, 2870, 1940, 1210, 980, 760, 640, 520, 412][i], [0.021, 0.034, 0.058, 0.081, 0.029, 0.018, 0.044, 0.026, 0.067, 0.052][i], [1620000, 980000, 540000, 310000, 190000, 170000, 95000, 160000, 88000, 29300][i]]),
      column_formats: { segment: "text", customers: "integer", churn_rate: "percent", revenue: "currency" },
    },
    {
      key: "plan_mix",
      label: "Customers by plan",
      columns: ["plan", "customers"],
      rows: [["Monthly", 8120], ["Annual", 6340], ["Two-year", 2210], ["Trial", 980], ["Legacy (grandfathered pricing)", 802], ["Partner", 640], ["Internal", 120], ["Other", 40]],
      column_formats: { plan: "text", customers: "integer" },
    },
    {
      key: "region_month_churn",
      label: "Churn by region and quarter",
      columns: ["region", "Q3 2024", "Q4 2024", "Q1 2025", "Q2 2025"],
      rows: [
        ["North America", 0.048, 0.044, 0.046, 0.039],
        ["Europe", 0.052, 0.049, 0.05, 0.045],
        ["APAC", 0.061, 0.057, 0.055, 0.049],
        ["LATAM", 0.071, 0.066, 0.064, 0.058],
      ],
      column_formats: { region: "text", "Q3 2024": "percent", "Q4 2024": "percent", "Q1 2025": "percent", "Q2 2025": "percent" },
    },
    {
      key: "at_risk_customers",
      label: "Customers at risk",
      columns: ["customer_id", "segment", "region", "tenure_months", "monthly_spend", "support_tickets", "churn_probability", "predicted_churn", "contract", "payment_method"],
      rows: customerRows,
      column_formats: { customer_id: "text", segment: "text", region: "text", tenure_months: "integer", monthly_spend: "currency", support_tickets: "integer", churn_probability: "percent", predicted_churn: "text", contract: "text", payment_method: "text" },
    },
  ],
  model: {
    type: "lightgbm_classifier",
    target: "churned",
    metrics: { auc: 0.871, accuracy: 0.912, f1: 0.684, precision: 0.731, recall: 0.643 },
    baseline_metrics: { auc: 0.5, accuracy: 0.871, f1: 0.0 },
    feature_importance: [
      { feature: "tenure_months", importance: 0.231 },
      { feature: "support_tickets_last_90d", importance: 0.184 },
      { feature: "contract_type", importance: 0.142 },
      { feature: "monthly_spend", importance: 0.117 },
      { feature: "days_since_last_login", importance: 0.098 },
      { feature: "payment_method", importance: 0.071 },
      { feature: "segment", importance: 0.054 },
      { feature: "number_of_seats_purchased_in_first_contract", importance: 0.041 },
      { feature: "region", importance: 0.032 },
      { feature: "discount_pct", importance: 0.03 },
    ],
    confusion_matrix: [
      [8210, 312],
      [497, 893],
    ],
    class_labels: ["Stayed", "Churned"],
  },
  stat_tests: [
    { key: "contract_vs_churn", test: "chi-square", statistic: 412.7, p_value: 0.0000012, n: 48213, conclusion: "Churn differs strongly by contract type." },
    { key: "tickets_vs_churn", test: "Mann-Whitney U", statistic: 1.82e7, p_value: 0.0031, n: 48213, conclusion: "Churned customers filed more support tickets." },
  ],
  insights_raw: [
    "Churn fell from 6.1% to 4.1% over 18 months.",
    "Startups churn about 4x more than Enterprise customers.",
    "Customers with more than 3 support tickets in 90 days are twice as likely to churn.",
  ],
};

export const sampleSpec: DashboardSpec = {
  title: "Customer churn dashboard",
  tabs: ["Overview", "Model", "Details"],
  filters: [{ id: "f_region", label: "Region", table_key: "at_risk_customers", column: "region" }],
  widgets: [
    // Overview — KPI row
    kpi("kpi_churn", "Churn rate", ["churn_rate"], 0, 0, 3),
    kpi("kpi_revenue", "Revenue (18 mo.)", ["total_revenue"], 3, 0, 3),
    kpi("kpi_customers", "Active customers", ["active_customers"], 6, 0, 3),
    kpi("kpi_more", "Other numbers", ["avg_tenure", "arpu", "events", "last_refresh"], 9, 0, 3),
    w({ id: "revenue_forecast", type: "forecast_with_interval", title: "Monthly revenue with 6-month forecast", subtitle: "Shaded band = 80% interval", binding: b("series", ["monthly_revenue", "revenue_forecast"]), layout: { x: 0, y: 2, w: 8, h: 4 }, x_label: "Month", y_label: "Revenue", format: "currency" }),
    w({ id: "insights_text", type: "text_insight", title: "What changed", binding: b("insights", []), layout: { x: 8, y: 2, w: 4, h: 4 }, text: "**Churn is trending down.** It fell from **6.1%** to **4.1%** over 18 months.\n\n- Startups churn ~4× more than Enterprise\n- Support tickets are the 2nd strongest signal\n- Annual contracts retain best" }),
    w({ id: "churn_trend", type: "line", title: "Monthly churn rate", binding: b("series", ["monthly_churn"]), layout: { x: 0, y: 6, w: 6, h: 4 }, x_label: "Month", y_label: "Churn rate", format: "percent" }),
    w({ id: "acq_vs_churn", type: "bar", title: "New vs churned customers", binding: b("series", ["new_customers", "churned_customers"]), layout: { x: 6, y: 6, w: 6, h: 4 }, x_label: "Month", y_label: "Customers", format: "integer" }),
    w({ id: "segment_churn", type: "bar", title: "Churn rate by segment (top 6)", binding: { ...b("tables", ["churn_by_segment"]), x_column: "segment", y_columns: ["churn_rate"], top_n: 6 }, layout: { x: 0, y: 10, w: 6, h: 4 }, orientation: "horizontal", x_label: "Churn rate", format: "percent" }),
    w({ id: "plan_mix", type: "pie", title: "Customers by plan", binding: { ...b("tables", ["plan_mix"]), x_column: "plan", y_columns: ["customers"] }, layout: { x: 6, y: 10, w: 6, h: 4 } }),
    // Model tab
    kpi("model_metrics", "Model quality", ["auc", "accuracy", "f1"], 0, 0, 12, "model"),
    w({ id: "feature_importance", type: "feature_importance", title: "What drives churn", binding: b("model", []), layout: { x: 0, y: 2, w: 7, h: 5 }, tab: "Model" }),
    w({ id: "confusion", type: "confusion_matrix", title: "Confusion matrix (test set)", binding: b("model", []), layout: { x: 7, y: 2, w: 5, h: 5 }, tab: "Model" }),
    w({ id: "tenure_spend", type: "scatter", title: "Tenure vs monthly spend", binding: b("series", ["tenure_vs_spend"]), layout: { x: 0, y: 7, w: 6, h: 4 }, tab: "Model", x_label: "Tenure (months)", y_label: "Monthly spend", format: "currency" }),
    w({ id: "tenure_hist", type: "histogram", title: "Customer tenure distribution", binding: b("series", ["tenure_hist"]), layout: { x: 6, y: 7, w: 6, h: 4 }, tab: "Model", x_label: "Tenure (months)", y_label: "Customers" }),
    // Details tab
    w({ id: "region_heatmap", type: "heatmap", title: "Churn by region and quarter", binding: { ...b("tables", ["region_month_churn"]), x_column: "region" }, layout: { x: 0, y: 0, w: 6, h: 4 }, tab: "Details", format: "percent" }),
    w({ id: "spend_hist", type: "histogram", title: "Monthly spend of at-risk customers", binding: { ...b("tables", ["at_risk_customers"]), y_columns: ["monthly_spend"] }, layout: { x: 6, y: 0, w: 6, h: 4 }, tab: "Details", format: "currency" }),
    w({ id: "at_risk_table", type: "table", title: "Customers at risk", subtitle: "Sorted by churn probability; use the column picker to show more", binding: b("tables", ["at_risk_customers"]), layout: { x: 0, y: 4, w: 8, h: 6 }, tab: "Details", hidden_columns: ["contract", "payment_method"] }),
    w({ id: "stat_tests", type: "table", title: "Statistical tests", binding: b("stat_tests", []), layout: { x: 8, y: 4, w: 4, h: 6 }, tab: "Details" }),
  ],
};

function b(source: DashboardSpec["widgets"][number]["binding"]["source"], keys: string[]) {
  return { source, keys, x_column: null, y_columns: [] as string[], top_n: null };
}

function w(p: Partial<DashboardSpec["widgets"][number]> & Pick<DashboardSpec["widgets"][number], "id" | "type" | "title" | "binding" | "layout">): DashboardSpec["widgets"][number] {
  return {
    subtitle: null,
    tab: "Overview",
    x_label: null,
    y_label: null,
    format: null,
    orientation: "vertical",
    stacked: false,
    hidden_columns: [],
    text: null,
    ...p,
  };
}

function kpi(id: string, title: string, keys: string[], x: number, y: number, width: number, source: "kpis" | "model" = "kpis") {
  return w({ id, type: "kpi", title, binding: b(source, keys), layout: { x, y, w: width, h: 2 }, tab: source === "model" ? "Model" : "Overview" });
}

export const sampleSanity: SanityReport = {
  status: "warn",
  checks_run: 15,
  checks_passed: 14,
  issues: [
    {
      severity: "medium",
      check: "row_accounting",
      message: "312 rows (0.6%) were dropped; reasons are documented.",
      suggested_fix: "",
      layer: 1,
    },
  ],
};

export const sampleQA: DashboardQAReport = {
  status: "pass",
  rounds: 1,
  screenshots: [],
  issues: [
    { severity: "low", widget_id: "plan_mix", rule: "pie_slices", message: "Pie had 8 slices; grouped the smallest into Other.", auto_fixed: true },
    { severity: "low", widget_id: "at_risk_table", rule: "wide_table", message: "Table has 10 columns; 2 hidden behind the column picker.", auto_fixed: true },
  ],
};

export const sampleInsights = `**Churn is down to 4.1%**, the lowest in 18 months, while revenue grew 44% year over year.

- **Startups** (8.1%) and **Retail** (6.7%) churn the most; Enterprise churns least (2.1%).
- The model (AUC **0.87**, vs. 0.50 baseline) says **tenure** and **recent support tickets** are the strongest churn signals.
- Revenue is forecast to reach **$353K** in December 2025 (80% interval $300K–$410K).`;
