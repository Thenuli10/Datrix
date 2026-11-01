"""Code Generator (Stage 4): writes the reusable analysis/ML module, the Layer-2
spot-check script, and drives the execute -> observe -> fix loop."""
import re
from dataclasses import dataclass
from typing import Any, Callable

from app.agents._common import load_prompt, to_json
from app.core.config import REPO_DIR, settings
from app.llm.base import LLMClient
from app.schemas.data import DatasetProfile
from app.schemas.plan import AnalysisPlan
from app.schemas.results import Results

FALLBACK_LIBS = ["pandas", "numpy", "scipy", "scikit-learn", "xgboost", "lightgbm", "statsmodels", "pyarrow",
                 "openpyxl", "joblib"]
IMPORT_NAMES = {"scikit-learn": "sklearn", "pyyaml": "yaml", "python-dateutil": "dateutil"}
REQUIREMENTS = REPO_DIR / "sandbox-image" / "requirements.txt"
LOG_TAIL = 4000

# Built through the schema so the prompt can never drift from app/schemas/results.py.
RESULTS_EXAMPLE = Results.model_validate({
    "summary": {"title": "Monthly revenue forecast", "rows_processed": 11850, "rows_dropped": 150,
                "drop_reasons": ["150 rows with missing order_date"],
                "input_date_min": "2023-01-01", "input_date_max": "2024-12-31"},
    "kpis": [{"key": "total_revenue", "label": "Total revenue", "value": 1534200.5, "format": "currency",
              "unit": "USD"},
             {"key": "growth_rate", "label": "YoY growth", "value": 0.124, "format": "percent"}],
    "series": [{"key": "monthly_revenue", "label": "Revenue", "x": ["2024-11-01", "2024-12-01"],
                "y": [120000.0, 131000.0], "x_label": "Month", "y_label": "Revenue (USD)", "kind": "line",
                "format": "currency"},
               {"key": "revenue_forecast", "label": "Forecast", "x": ["2025-01-01", "2025-02-01"],
                "y": [133500.0, 128900.0], "y_lower": [121000.0, 114200.0], "y_upper": [146000.0, 143600.0],
                "is_forecast": True, "x_label": "Month", "y_label": "Revenue (USD)", "format": "currency"}],
    "tables": [{"key": "top_products", "label": "Top products", "columns": ["product", "revenue", "share"],
                "rows": [["A", 52000.0, 0.34], ["B", 31000.0, None]],
                "column_formats": {"revenue": "currency", "share": "percent"}}],
    "model": {"type": "lightgbm_regressor", "target": "revenue", "metrics": {"mape": 0.081, "rmse": 9100.0},
              "baseline_metrics": {"mape": 0.142, "rmse": 15800.0},
              "feature_importance": [{"feature": "month", "importance": 0.41},
                                     {"feature": "promo_count", "importance": 0.22}],
              "confusion_matrix": None, "class_labels": None},
    "stat_tests": [{"key": "promo_effect", "test": "Welch t-test", "statistic": 3.21, "p_value": 0.0014,
                    "n": 730, "conclusion": "Promo days have significantly higher revenue (p < 0.01)."}],
    "insights_raw": ["Revenue grew 12.4% year over year", "Product A drives 34% of revenue"],
})


def allowed_libs() -> list[str]:
    """Package list from sandbox-image/requirements.txt (fallback: built-in list)."""
    try:
        lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return FALLBACK_LIBS
    libs = [re.split(r"[<>=!~\[;\s]", ln.strip(), maxsplit=1)[0] for ln in lines]
    return [x for x in libs if x and not x.startswith(("#", "-"))] or FALLBACK_LIBS


def _libs_text() -> str:
    return ", ".join(f"{p} (import {IMPORT_NAMES[p.lower()]})" if p.lower() in IMPORT_NAMES else p
                     for p in allowed_libs())


def system_prompt(name: str = "coder") -> str:
    return (load_prompt(name).replace("{{ALLOWED_LIBS}}", _libs_text())
            .replace("{{RESULTS_EXAMPLE}}", RESULTS_EXAMPLE.model_dump_json(indent=1)))


def strip_code_fences(text: str) -> str:
    """Extract Python source from a reply that may wrap it in markdown fences."""
    blocks = re.findall(r"```[ \t]*(?:python|py)?[ \t]*\r?\n(.*?)```", text, flags=re.S | re.I)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip().removeprefix("```python").removeprefix("```").removesuffix("```").strip() + "\n"


def _entry_points(plan: AnalysisPlan) -> str:
    if plan.path == "ml":
        return ("PATH: ml. Define exactly `train(input_dir, output_dir, params)` and "
                "`predict(input_dir, model_path, output_dir, params)`.")
    return "PATH: script. Define exactly `run(input_dir: str, output_dir: str, params: dict) -> None`."


def generate(llm: LLMClient, plan: AnalysisPlan, profiles_canonical: list[DatasetProfile], manifest: dict[str, Any],
             pid: int | None, feedback: str | None = None, previous_code: str | None = None) -> str:
    """Python source implementing the plan against the fixed interface."""
    profiles = [{"file_name": p.file_name, "row_count": p.row_count,
                 "columns": [c.model_dump(mode="json", exclude={"sample_values"}) for c in p.columns],
                 "sample_rows": p.sample_rows[:min(5, settings.llm_sample_rows)]} for p in profiles_canonical]
    user = (f"{_entry_points(plan)}\n\n## Approved plan\n{to_json(plan)}\n\n"
            f"## input_dir/manifest.json\n{to_json(manifest)}\n\n"
            f"## Input profiles (canonical column names)\n{to_json(profiles)}")
    if previous_code:
        user += f"\n\n## Previous version of the code\n```python\n{previous_code}\n```"
    if feedback:
        user += (f"\n\n## Problems to fix\n{feedback}\n\nReturn the COMPLETE corrected file, "
                 "not a diff. Fix the root cause.")
    return strip_code_fences(llm.text(agent="coder", system=system_prompt(), user=user, project_id=pid))


def _results_digest(results: Results | dict[str, Any]) -> dict[str, Any]:
    r = results if isinstance(results, Results) else Results.model_validate(results)
    return {"summary": r.summary.model_dump(mode="json"),
            "kpis": [k.model_dump(mode="json") for k in r.kpis],
            "tables": [{"key": t.key, "columns": t.columns, "first_rows": t.rows[:5], "n_rows": len(t.rows)}
                       for t in r.tables],
            "series": [{"key": s.key, "n_points": len(s.x), "first_x": s.x[:3], "first_y": s.y[:3],
                        "is_forecast": s.is_forecast} for s in r.series],
            "model": r.model.model_dump(mode="json", include={"type", "target", "metrics"}) if r.model else None}


def generate_spot_check(llm: LLMClient, plan: AnalysisPlan, results: Results | dict[str, Any],
                        manifest: dict[str, Any], pid: int | None) -> str:
    """Source of `def spot_check(input_dir: str) -> list[dict]` recomputing 2-3 key numbers with pandas."""
    user = (f"## Approved plan\n{to_json(plan)}\n\n## input_dir/manifest.json\n{to_json(manifest)}\n\n"
            f"## results.json (digest)\n{to_json(_results_digest(results))}")
    return strip_code_fences(llm.text(agent="coder_spot_check", system=system_prompt("coder_spot_check"),
                                      user=user, project_id=pid))


@dataclass
class StaticCheckFailure:
    """SandboxResult-like value for code rejected by the static check before running."""
    error: str
    ok: bool = False
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    results: dict[str, Any] | None = None
    duration_s: float = 0.0


def _static_violations(code: str) -> list[str]:
    try:
        from app.sandbox.static_check import check_code
    except ImportError:
        return []
    return list(check_code(code))


def _failure_feedback(result: Any) -> str:
    parts = [f"Execution failed: {getattr(result, 'error', None) or 'unknown error'}"]
    if stderr := (getattr(result, "stderr", "") or "")[-LOG_TAIL:]:
        parts.append(f"stderr (tail):\n{stderr}")
    if stdout := (getattr(result, "stdout", "") or "")[-LOG_TAIL // 2:]:
        parts.append(f"stdout (tail):\n{stdout}")
    return "\n\n".join(parts)


def fix_loop(llm: LLMClient, plan: AnalysisPlan, profiles: list[DatasetProfile], manifest: dict[str, Any],
             pid: int | None, run_fn: Callable[[str], Any], on_log: Callable[[str], None] | None = None,
             feedback: str | None = None, previous_code: str | None = None) -> tuple[str, Any]:
    """Generate -> static check -> run, feeding errors back, up to settings.max_fix_attempts.

    `run_fn(code)` returns a SandboxResult-like object (.ok/.error/.stderr/.stdout).
    Returns (last code, last result)."""
    say = on_log or (lambda _msg: None)
    code, result = previous_code or "", None
    for attempt in range(1, settings.max_fix_attempts + 1):
        say(f"Generating code (attempt {attempt}/{settings.max_fix_attempts})")
        code = generate(llm, plan, profiles, manifest, pid, feedback=feedback, previous_code=previous_code)
        previous_code = code
        if violations := _static_violations(code):
            say(f"Static check rejected the code: {'; '.join(violations)}")
            feedback = "Static safety check rejected the code (it was NOT run):\n- " + "\n- ".join(violations)
            result = StaticCheckFailure(error=feedback)
            continue
        say("Running code in sandbox")
        result = run_fn(code)
        if getattr(result, "ok", False):
            say("Code ran successfully")
            return code, result
        feedback = _failure_feedback(result)
        say(f"Run failed: {getattr(result, 'error', None) or 'see logs'}")
    return code, result
