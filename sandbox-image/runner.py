"""Sandbox entry point: import the generated module, call its entry function, validate output.

    python runner.py --entry run|train|predict|spot_check --code /code/code.py
        --input /input --output /output [--model /model] --params /code/params.json

Entries (PLAN.md §3 Stage 4):
    run(input_dir, output_dir, params)                      -> writes results.json
    train(input_dir, output_dir, params)                    -> params["model_dir"] = --model
    predict(input_dir, model_path, output_dir, params)      -> model_path = --model (directory)
    spot_check(input_dir) -> list[dict]                     -> runner writes spot_check.json

Exit 0 on success. On any failure prints `::error::<message>` to stdout (traceback to stderr)
and exits 1. Stdlib only: this file must not depend on anything but the image's Python.
Keep the structural check in sync with backend/app/schemas/results.py.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

RESULTS_FILE = "results.json"
SPOT_CHECK_FILE = "spot_check.json"


class ValidationError(Exception):
    """results.json does not match the contract."""


def fail(message: str) -> None:
    """Report a failure in the `::error::` format the sandbox manager parses, then exit 1."""
    one_line = " ".join(str(message).split())
    print(f"::error::{one_line}", flush=True)
    sys.exit(1)


def _reject_constant(name: str) -> Any:
    raise ValidationError(f"results.json contains non-finite number {name} (NaN/Infinity are not allowed)")


def load_strict_json(path: Path) -> Any:
    """Parse JSON, rejecting NaN / Infinity / -Infinity."""
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_finite(obj: Any, where: str) -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ValidationError(f"{where}: non-finite number")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _check_finite(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_finite(v, f"{where}[{i}]")


def _items(results: dict, section: str, required: tuple[str, ...] = ()) -> list[dict]:
    value = results.get(section, [])
    if not isinstance(value, list):
        raise ValidationError(f"'{section}' must be a list")
    seen: set[str] = set()
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValidationError(f"{section}[{i}] must be an object")
        key = item.get("key")
        if not isinstance(key, str) or not key:
            raise ValidationError(f"{section}[{i}] needs a non-empty string 'key'")
        if key in seen:
            raise ValidationError(f"duplicate key '{key}' in '{section}'")
        seen.add(key)
        for field in required:
            if field not in item:
                raise ValidationError(f"{section}['{key}'] is missing '{field}'")
    return value


def validate_results(results: Any) -> None:
    """Lightweight structural check of results.json (PLAN.md §7)."""
    if not isinstance(results, dict):
        raise ValidationError("results.json must be a JSON object")
    summary = results.get("summary")
    if not isinstance(summary, dict):
        raise ValidationError("'summary' object is required")
    if not isinstance(summary.get("title"), str) or not summary["title"].strip():
        raise ValidationError("summary.title must be a non-empty string")
    if not _is_int(summary.get("rows_processed")):
        raise ValidationError("summary.rows_processed must be an integer")

    _items(results, "kpis", ("label", "value"))
    for s in _items(results, "series", ("x", "y")):
        if not isinstance(s["x"], list) or not isinstance(s["y"], list):
            raise ValidationError(f"series['{s['key']}'] x and y must be lists")
        if len(s["x"]) != len(s["y"]):
            raise ValidationError(f"series['{s['key']}'] x has {len(s['x'])} values but y has {len(s['y'])}")
        for bound in ("y_lower", "y_upper"):
            b = s.get(bound)
            if b is not None and (not isinstance(b, list) or len(b) != len(s["y"])):
                raise ValidationError(f"series['{s['key']}'] {bound} must be a list as long as y")
    for t in _items(results, "tables", ("columns", "rows")):
        cols, rows = t["columns"], t["rows"]
        if not isinstance(cols, list) or not isinstance(rows, list):
            raise ValidationError(f"tables['{t['key']}'] columns and rows must be lists")
        for i, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(cols):
                raise ValidationError(f"tables['{t['key']}'] row {i} must be a list of {len(cols)} values")
    _items(results, "stat_tests", ("test", "n"))

    model = results.get("model")
    if model is not None:
        if not isinstance(model, dict) or not isinstance(model.get("type"), str):
            raise ValidationError("'model' must be an object with a string 'type'")
        if not isinstance(model.get("metrics"), dict):
            raise ValidationError("model.metrics must be an object")
    insights = results.get("insights_raw", [])
    if not isinstance(insights, list) or not all(isinstance(x, str) for x in insights):
        raise ValidationError("'insights_raw' must be a list of strings")
    _check_finite(results, "results")


def _json_default(obj: Any) -> Any:
    """Convert numpy / pandas scalars (and dates) without importing them."""
    if hasattr(obj, "item"):
        return obj.item()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "tolist"):
        return obj.tolist()
    raise TypeError(f"{type(obj).__name__} is not JSON serializable")


def load_module(code_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("generated_code", code_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {code_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["generated_code"] = module
    spec.loader.exec_module(module)
    return module


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Datrix sandbox runner")
    p.add_argument("--entry", required=True, choices=["run", "train", "predict", "spot_check"])
    p.add_argument("--code", required=True, type=Path)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--model", type=Path, default=None)
    p.add_argument("--params", type=Path, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    params: dict[str, Any] = {}
    if args.params is not None and args.params.exists():
        params = json.loads(args.params.read_text(encoding="utf-8") or "{}")
    if args.entry in ("train", "predict") and args.model is None:
        fail(f"--model is required for entry '{args.entry}'")

    inp, out = str(args.input), str(args.output)
    try:
        module = load_module(args.code)
    except BaseException as exc:  # noqa: BLE001 - syntax errors etc. must surface
        traceback.print_exc()
        fail(f"importing code failed: {type(exc).__name__}: {exc}")

    fn = getattr(module, args.entry, None)
    if not callable(fn):
        fail(f"code does not define a function '{args.entry}'")

    try:
        if args.entry == "run":
            fn(inp, out, params)
        elif args.entry == "train":
            params["model_dir"] = str(args.model)
            fn(inp, out, params)
        elif args.entry == "predict":
            params["model_dir"] = str(args.model)
            fn(inp, str(args.model), out, params)
        else:
            checks = fn(inp)
    except BaseException as exc:  # noqa: BLE001 - includes SystemExit from user code
        traceback.print_exc()
        fail(f"{args.entry}() raised {type(exc).__name__}: {exc}")

    try:
        if args.entry == "spot_check":
            if not isinstance(checks, list) or not all(isinstance(c, dict) for c in checks):
                raise ValidationError("spot_check() must return a list of dicts")
            text = json.dumps(checks, default=_json_default, allow_nan=False)
            (args.output / SPOT_CHECK_FILE).write_text(text, encoding="utf-8")
        else:
            path = args.output / RESULTS_FILE
            if not path.exists():
                raise ValidationError(f"{args.entry}() did not write {RESULTS_FILE} to output_dir")
            validate_results(load_strict_json(path))
    except (ValidationError, ValueError, TypeError) as exc:
        fail(f"invalid output: {exc}")
    print(f"runner: {args.entry} finished OK", flush=True)


if __name__ == "__main__":
    main()
