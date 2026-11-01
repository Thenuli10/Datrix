# Module interfaces (build contract)

The spec is [PLAN.md](PLAN.md). This file pins the **Python signatures between backend modules** so they can be
built in parallel. Pydantic contracts live in `backend/app/schemas/*`, DB tables in `backend/app/models/tables.py`,
settings in `backend/app/core/config.py`, LLM interface in `backend/app/llm/base.py`. Do not change those without
updating every user. All paths are `pathlib.Path`. Python ≥ 3.12, backend runs on 3.13 locally.

## llm/
- `openai_client.py`: `class OpenAIClient(LLMClient)` — OpenAI SDK, `client.beta.chat.completions.parse` /
  `responses` structured outputs from Pydantic, tool calling, vision via base64 PNG; logs every call to `LLMCall`
  (tokens, cost estimate, latency) in its own DB session.
- `fake.py`: `class FakeLLMClient(LLMClient)` — deterministic, registry of canned responses per `agent` name
  (`fake.register(agent, response_or_callable)`); falls back to building a minimal valid instance of the schema.
- `__init__.py`: `get_llm() -> LLMClient` (Fake when `settings.llm_fake` or no API key in tests).

## services/
- `storage.py`: `project_dir(pid)`, `upload_path(pid, dataset_id, ext)`, `pipeline_dir(pid, version)`,
  `run_dir(pid, run_id)` — create dirs, return Paths.
- `profiler.py`: `load_dataframe(path, file_type) -> pd.DataFrame`;
  `profile_file(path, file_type, dataset_id, file_name, sample_rows=settings.llm_sample_rows) -> DatasetProfile`
  (DuckDB for csv/parquet stats, pandas fallback); `template_csv(spec: DataSpec) -> str`.
- `contract.py`: `freeze_contract(datasets: list[(file_name, df)], report: ValidationReport, spec: DataSpec) -> DataContract`;
  `check_contract(contract, datasets: list[(file_name, df)], mapping_override: dict[str,str]|None=None) -> ContractCheckResult`
  (deterministic, no LLM); `apply_mapping(contract, datasets) -> list[pd.DataFrame]` renames to canonical names.
- `drift.py`: `training_profile(df) -> dict` (bins/quantiles per numeric col, freqs per categorical);
  `check_drift(training_profile: dict, df) -> DriftReport` (PSI for categorical/binned, KS via stored sample for numeric).
- `inputs.py`: `prepare_inputs(datasets, mapping, joins, out_dir) -> Path` writes canonical, mapped files to an input dir
  as `/input/<name>.parquet` plus `/input/manifest.json` `{files:[...], columns:{...}, joins:[...]}`.
- `jobs.py`: `JobRunner` — `submit(coro_fn, *args)` runs in background asyncio tasks; `LogBus` with
  `publish(run_id, line)` / `subscribe(run_id) -> AsyncIterator[str]` for SSE; lines also appended to the run's logs.txt.
- `orchestrator.py`: the state machine (§4). Functions (sync, run inside JobRunner via `asyncio.to_thread`):
  `analyze_requirement(session, project)`, `answer_message(session, project, text)`, `validate(session, project)`,
  `propose_plan(session, project)`, `approve_plan(session, project, edited_plan|None) -> Run`,
  `execute_first_run(run_id)`, `rerun(pipeline_id, dataset_ids, mode, data_mode) -> Run`, `execute_rerun(run_id)`.
- `screenshot.py`: `capture(run_id, out_dir) -> list[Path]` Playwright headless Chromium on
  `{frontend_url}/render/runs/{id}` at 1440 & 390 widths × light & dark (`?theme=`); also returns DOM findings
  (overflow, cut-off text, font < 11px, WCAG AA contrast) via `page.evaluate`: `capture(...) -> (paths, list[DashboardIssue])`.
  Must degrade gracefully (return `[], []`) if Playwright/browser or frontend is unavailable.

## sandbox/
- `static_check.py`: `check_code(source: str) -> list[str]` (AST: banned imports subprocess, socket, requests,
  urllib, http, ftplib, smtplib, ctypes, multiprocessing, shutil.rmtree, os.system/popen/exec*/fork/spawn*, eval,
  exec, compile, __import__, open() outside /output or /input paths is allowed only via params; size limit 200 KB).
- `manager.py`: `run_in_sandbox(code: str, entry: "run"|"train"|"predict", input_dir, output_dir, params: dict,
  model_dir: Path|None, on_log: Callable[[str],None], timeout_s=None) -> SandboxResult(ok, exit_code, stdout, stderr,
  results: dict|None, error: str|None, duration_s)`. Docker backend per §5 (network none, mem/cpu/pids limits,
  read_only root, tmpfs /tmp, /input ro, /code ro, /output rw, /model ro|rw, user 1000, no-new-privileges,
  cap_drop ALL, killed on timeout). `settings.sandbox_backend == "local"` → subprocess fallback running the same
  `sandbox-image/runner.py` (dev only, no isolation). `ensure_image()` builds `sandbox-image/` if missing.
  `run_spot_check(code, input_dir, output_dir) -> dict` runs a spot-check script (`def spot_check(input_dir) -> list[dict]`).
- `sandbox-image/runner.py`: `python runner.py --entry run --code /code/code.py --input /input --output /output
  [--model /model] --params /code/params.json` imports module, calls entry, validates `results.json` shape, exits 0/1,
  prints `::error::<msg>` on failure.

## agents/  (each takes `llm: LLMClient` and returns schema objects; prompts in `agents/prompts/<name>.md`)
- `analyst.py`: `analyze(llm, requirement, context: dict, messages: list[(role, text)], pid) -> RequirementAnalysis`
- `validator.py`: `validate(llm, spec, profiles: list[DatasetProfile], dfs: dict[int, DataFrame], pid) -> ValidationReport`
  (tool loop with get_profile, get_sample, column_stats, value_counts, check_join; samples capped at settings.llm_sample_rows)
- `planner.py`: `plan(llm, requirement, analysis, report, profiles, pid) -> AnalysisPlan`
- `coder.py`: `generate(llm, plan, profiles_canonical, manifest, pid, feedback: str|None=None, previous_code: str|None=None) -> str`
  (fixed interface: script `run(input_dir, output_dir, params)`; ML `train(...)` + `predict(input_dir, model_path, output_dir, params)`;
  must write `results.json` per §7; lib list = sandbox-image/requirements.txt); `generate_spot_check(llm, plan, results, manifest, pid) -> str`.
  Helper `fix_loop(llm, plan, ..., run_fn) -> (code, SandboxResult)` max `settings.max_fix_attempts`.
- `sanity.py`: `review(llm, requirement, plan, profiles, results, findings: list[SanityIssue], pid) -> SanityReport` (Layer 3).
- `composer.py`: `compose(llm, results: Results, plan, pid, qa_issues: list[DashboardIssue]|None=None, previous: DashboardSpec|None=None) -> DashboardSpec`
- `dashboard_qa.py`: `review(llm, spec, screenshots: list[bytes], findings, pid) -> list[DashboardIssue]` (vision).
- `insights.py`: `write(llm, requirement, results, pid) -> str` markdown.
- `automap.py`: `suggest_mapping(llm, contract, profiles, pid) -> dict[str,str]` for failed contract checks.

## checks/  (pure code, no LLM, no I/O)
- `sanity_rules.py`: `run_layer1(results: Results, input_rows: int, input_date_range: (min,max)|None, plan: AnalysisPlan) -> (list[SanityIssue], checks_run, checks_passed)`;
  `compare_spot_checks(spot: list[SpotCheck], results) -> list[SanityIssue]`; `summarize(issues, run, passed) -> SanityReport`.
- `dashboard_rules.py`: `check_and_fix(spec: DashboardSpec, results: Results) -> (DashboardSpec, list[DashboardIssue])`
  applies auto-fixes from §7b table (re-pack, top-N, pie→bar, horizontal bar for long labels, formats, remove empty,
  hidden_columns, move overflow to "Details" tab); unfixable ones (missing title/axis) returned with auto_fixed=False.
- `run_compare.py`: `compare(prev: Results, curr: Results) -> list[SanityIssue]` (KPI jump, metric drop, missing keys).

## api/  (FastAPI routers, prefix-free paths exactly as PLAN.md §8, plus:)
- `GET /projects/{id}/datasets`, `GET /projects/{id}/validation`, `GET /projects/{id}/plan`, `GET /projects/{id}/runs`,
  `GET /runs/{id}/dashboard` (spec + results + sanity + qa + insights in one payload), `GET /runs/{id}/thumbnail`,
  `GET /pipelines` list, `GET /pipelines/{id}/code` (not shown in UI by default).
- `POST /pipelines/{id}/runs` multipart: files + `mode` (predict|retrain|script) + `data_mode` (replace|append).
