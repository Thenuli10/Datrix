"use client";
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Data } from "plotly.js";
import { ExternalLink, GitFork, LayoutDashboard, Play, ScrollText, Wand2 } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { useIdParam, useInterval, useLoad, useSingleFlight } from "@/lib/hooks";
import type { DataMode, Run, RunWithKpis, RerunMode } from "@/lib/types";
import { formatDateTime, formatValue, plotlyHoverFormat, plotlyTickFormat, toNumber } from "@/lib/format";
import { isRunActive } from "@/lib/utils";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { RadioCards } from "@/components/ui/radio-cards";
import { Select } from "@/components/ui/select";
import { PageSkeleton, Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { EmptyState, PageHeader, PathBadge, RunStatusBadge } from "@/components/layout/common";
import { FileDropzone } from "@/components/project/FileDropzone";
import { ContractCheckView, StageIndicator } from "@/components/run/RunProgress";
import { DriftAlert } from "@/components/dashboard/DashboardView";
import { PlotlyChart } from "@/components/dashboard/PlotlyChart";

const SANITY_VARIANT = { pass: "success", warn: "warning", fail: "destructive" } as const;

function modeLabel(m: Run["mode"]) {
  return m === "train" ? "Retrain" : m === "predict" ? "Predict" : "Script";
}

/* ------------------------------------------------------------------ */

function KpiTrend({ runs }: { runs: RunWithKpis[] }) {
  const done = React.useMemo(() => [...runs].filter((r) => r.status === "COMPLETED" && r.kpis?.length).reverse(), [runs]);
  const keys = React.useMemo(() => {
    const m = new Map<string, string>();
    for (const r of done) for (const k of r.kpis) if (toNumber(k.value) !== null && !m.has(k.key)) m.set(k.key, k.label);
    return Array.from(m.entries());
  }, [done]);
  const [key, setKey] = React.useState<string>("");
  React.useEffect(() => {
    if (!keys.some(([k]) => k === key)) setKey(keys[0]?.[0] ?? "");
  }, [keys, key]);

  const points = done
    .map((r) => ({ r, k: r.kpis.find((k) => k.key === key) }))
    .filter((p) => p.k && toNumber(p.k.value) !== null);
  const fmt = points[0]?.k?.format;

  const build = React.useCallback(
    (t: { palette: string[] }) => ({
      data: [
        {
          type: "scatter",
          mode: "lines+markers",
          x: points.map((p) => `#${p.r.id}`),
          y: points.map((p) => toNumber(p.k!.value)),
          customdata: points.map((p) => formatDateTime(p.r.finished_at ?? p.r.started_at)),
          hovertemplate: `Run %{x}<br>%{customdata}<br>%{y${plotlyHoverFormat(fmt) ? `:${plotlyHoverFormat(fmt)}` : ""}}<extra></extra>`,
          line: { color: t.palette[0], width: 2 },
          marker: { size: 8, color: t.palette[0] },
        } as Data,
      ],
      layout: {
        showlegend: false,
        xaxis: { type: "category" as const, title: { text: "Run" } },
        yaxis: { tickformat: plotlyTickFormat(fmt) },
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key, done, fmt],
  );

  if (done.length < 1 || !keys.length) return null;
  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle>KPI over runs</CardTitle>
          <CardDescription>How a key number changed each time new data was run.</CardDescription>
        </div>
        <div>
          <label htmlFor="kpi-trend" className="sr-only">
            KPI
          </label>
          <Select id="kpi-trend" wrapperClassName="w-56 max-w-full" value={key} onChange={(e) => setKey(e.target.value)}>
            {keys.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </Select>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <PlotlyChart key={key} build={build} ariaLabel="KPI over runs" />
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function AutomapDialog({
  open,
  onOpenChange,
  mapping,
  onChange,
  options,
  onRetry,
  retrying,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  mapping: Record<string, string>;
  onChange: (m: Record<string, string>) => void;
  options: string[];
  onRetry: () => void;
  retrying: boolean;
}) {
  const entries = Object.entries(mapping);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Suggested column mapping"
      description="Columns the saved pipeline expects (left) mapped to columns in your new files (right). Adjust if needed, then retry."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={onRetry} loading={retrying} disabled={!entries.length}>
            <Play /> Retry with this mapping
          </Button>
        </>
      }
    >
      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">No mapping could be suggested. Consider forking the pipeline instead.</p>
      ) : (
        <ul className="space-y-3">
          {entries.map(([src, dst]) => (
            <li key={src} className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
              <code className="truncate rounded bg-muted px-1.5 py-1 text-xs" title={src}>
                {src}
              </code>
              <span aria-hidden className="text-muted-foreground">
                →
              </span>
              <div>
                <label htmlFor={`am-${src}`} className="sr-only">
                  New column for {src}
                </label>
                {options.length ? (
                  <Select id={`am-${src}`} value={dst} onChange={(e) => onChange({ ...mapping, [src]: e.target.value })}>
                    {!options.includes(dst) && <option value={dst}>{dst}</option>}
                    {options.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <input
                    id={`am-${src}`}
                    value={dst}
                    onChange={(e) => onChange({ ...mapping, [src]: e.target.value })}
                    className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm"
                  />
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */

export default function PipelinePage() {
  const id = useIdParam();
  const router = useRouter();
  const toast = useToast();
  const pipeline = useLoad(() => api.getPipeline(id), [id]);
  const runs = useLoad(() => api.listPipelineRuns(id), [id]);

  const [files, setFiles] = React.useState<File[]>([]);
  const [dataMode, setDataMode] = React.useState<DataMode | null>(null);
  const [mode, setMode] = React.useState<RerunMode | null>(null);
  const [progress, setProgress] = React.useState<number | null>(null);
  const [activeRun, setActiveRun] = React.useState<Run | null>(null);
  const [automapOpen, setAutomapOpen] = React.useState(false);
  const [automap, setAutomap] = React.useState<Record<string, string>>({});
  const [automapOptions, setAutomapOptions] = React.useState<string[]>([]);
  const [mapping, setMapping] = React.useState(false);
  const [retrying, setRetrying] = React.useState(false);
  const [forking, setForking] = React.useState(false);
  const once = useSingleFlight();

  const pl = pipeline.data;
  const isML = pl?.path === "ml";

  // Poll the run we just started.
  const pollRun = React.useCallback(async () => {
    if (!activeRun) return;
    try {
      const r = await api.getRun(activeRun.id);
      setActiveRun(r);
      if (!isRunActive(r.status)) {
        void runs.reload();
        if (r.status === "COMPLETED") toast.success(`Run #${r.id} completed`);
      }
    } catch {
      /* transient */
    }
  }, [activeRun, runs, toast]);
  useInterval(() => void pollRun(), 2000, !!activeRun && isRunActive(activeRun.status));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pl || !files.length || !dataMode || (isML && !mode)) return;
    void once(async () => {
      setProgress(0);
      try {
        const r = await api.createPipelineRun(id, { files, mode: isML ? mode! : "script", data_mode: dataMode }, setProgress);
        setActiveRun(r);
        setFiles([]);
        toast.info(`Run #${r.id} started`, "Checking the data contract first.");
        void runs.reload();
      } catch (err) {
        toast.error("Could not start run", errorMessage(err));
      } finally {
        setProgress(null);
      }
    });
  };

  const doAutomap = () => once(automapNow);
  const automapNow = async () => {
    if (!activeRun) return;
    setMapping(true);
    try {
      const [m, ds] = await Promise.all([
        api.automap(id, activeRun.dataset_ids),
        pl ? api.listDatasets(pl.project_id).catch(() => []) : Promise.resolve([]),
      ]);
      const suggested = { ...(activeRun.contract_check_json?.suggested_mapping ?? {}), ...m };
      setAutomap(suggested);
      const cols = ds
        .filter((d) => activeRun.dataset_ids.includes(d.id))
        .flatMap((d) => d.profile_json?.columns.map((c) => c.name) ?? []);
      setAutomapOptions(Array.from(new Set(cols)).sort());
      setAutomapOpen(true);
    } catch (err) {
      toast.error("Auto-map failed", errorMessage(err));
    } finally {
      setMapping(false);
    }
  };

  const retry = () => once(retryNow);
  const retryNow = async () => {
    if (!activeRun) return;
    setRetrying(true);
    try {
      const r = await api.retryPipelineRun(id, activeRun.id, {
        mapping_override: automap,
        data_mode: activeRun.contract_check_json?.data_mode,
      });
      setAutomapOpen(false);
      setActiveRun(r);
      toast.info(`Retrying as run #${r.id}`);
      void runs.reload();
    } catch (err) {
      toast.error("Retry failed", errorMessage(err));
    } finally {
      setRetrying(false);
    }
  };

  const fork = async () => {
    if (!window.confirm("Fork this pipeline? You'll go back to the plan step to build a new version for the new data shape.")) return;
    setForking(true);
    try {
      const { project_id } = await api.forkPipeline(id);
      router.push(`/projects/${project_id}/plan`);
    } catch (err) {
      toast.error("Fork failed", errorMessage(err));
      setForking(false);
    }
  };

  if (pipeline.loading && !pl) return <PageSkeleton />;
  if (!pl) return <Alert variant="destructive" title="Could not load pipeline">{pipeline.error}</Alert>;

  const uploading = progress !== null;
  const contractFailed = activeRun?.status === "FAILED" && activeRun.contract_check_json?.ok === false;
  const latestDone = runs.data?.find((r) => r.status === "COMPLETED");
  const canSubmit = files.length > 0 && !!dataMode && (!isML || !!mode) && !uploading;

  return (
    <>
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-2">
            Pipeline v{pl.version} <PathBadge path={pl.path} />
          </span>
        }
        title={pl.project_name || `Project #${pl.project_id}`}
        description="Upload new data of the same shape. It is checked against the saved data contract, then the saved script or model runs and the same dashboard refreshes."
        actions={
          <>
            {latestDone && (
              <Link href={`/projects/${pl.project_id}/dashboard?run=${latestDone.id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
                <LayoutDashboard /> Latest dashboard
              </Link>
            )}
            <Button variant="ghost" size="sm" onClick={() => void fork()} loading={forking}>
              <GitFork /> Fork pipeline
            </Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Run on new data</CardTitle>
              <CardDescription>Choose how the new data is used each time. Nothing is assumed.</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={submit} className="space-y-5">
                <FileDropzone files={files} onChange={setFiles} disabled={uploading} label="Drop the new data files here" />
                <RadioCards<DataMode>
                  legend="Data"
                  required
                  value={dataMode}
                  onChange={setDataMode}
                  disabled={uploading}
                  options={[
                    { value: "replace", label: "Replace", description: "Use only the new files." },
                    { value: "append", label: "Append", description: "Combine the new files with the previous data." },
                  ]}
                />
                {isML ? (
                  <RadioCards<RerunMode>
                    legend="Model"
                    required
                    value={mode}
                    onChange={setMode}
                    disabled={uploading}
                    options={[
                      { value: "predict", label: "Predict with existing model", description: "Fast. Uses the saved model as-is." },
                      { value: "retrain", label: "Retrain", description: "Train a fresh model on this data, then predict." },
                    ]}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">The saved analysis script will run on the new data.</p>
                )}
                {uploading && (
                  <div className="space-y-1" aria-live="polite">
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full bg-primary transition-all" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
                    </div>
                    <p className="text-xs text-muted-foreground">Uploading… {Math.round((progress ?? 0) * 100)}%</p>
                  </div>
                )}
                <Button type="submit" disabled={!canSubmit} loading={uploading}>
                  <Play /> Check contract & run
                </Button>
                {!canSubmit && files.length > 0 && !uploading && (
                  <p className="text-xs text-muted-foreground">Choose {!dataMode ? "replace or append" : ""}{!dataMode && isML && !mode ? " and " : ""}{isML && !mode ? "predict or retrain" : ""} to continue.</p>
                )}
              </form>
            </CardContent>
          </Card>

          {activeRun && (
            <Card aria-live="polite">
              <CardHeader className="flex-row items-start justify-between gap-3">
                <div className="space-y-1">
                  <CardTitle className="flex items-center gap-2">
                    Run #{activeRun.id} <RunStatusBadge status={activeRun.status} />
                  </CardTitle>
                  <CardDescription>
                    {modeLabel(activeRun.mode)} · {activeRun.contract_check_json?.data_mode ?? "replace"} data · {activeRun.stage}
                  </CardDescription>
                </div>
                <Link href={`/projects/${activeRun.project_id}/run?run=${activeRun.id}`} className={buttonVariants({ variant: "ghost", size: "sm" })}>
                  <ScrollText /> Logs
                </Link>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 md:grid-cols-[14rem_minmax(0,1fr)]">
                  <StageIndicator run={activeRun} />
                  <div className="min-w-0 space-y-3">
                    <ContractCheckView check={activeRun.contract_check_json} />
                    <DriftAlert drift={activeRun.drift_json} />
                    {activeRun.status === "FAILED" && !contractFailed && (
                      <Alert variant="destructive" title="Run failed">
                        <p className="whitespace-pre-wrap break-words">{activeRun.error}</p>
                      </Alert>
                    )}
                    {contractFailed && (
                      <div className="flex flex-wrap gap-2">
                        <Button onClick={() => void doAutomap()} loading={mapping}>
                          <Wand2 /> Auto-map columns
                        </Button>
                        <Button variant="outline" onClick={() => void fork()} loading={forking}>
                          <GitFork /> Fork pipeline → back to plan
                        </Button>
                      </div>
                    )}
                    {activeRun.status === "COMPLETED" && (
                      <Link href={`/projects/${activeRun.project_id}/dashboard?run=${activeRun.id}`} className={buttonVariants()}>
                        <LayoutDashboard /> Open dashboard
                      </Link>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          <KpiTrend runs={runs.data ?? []} />

          <Card>
            <CardHeader>
              <CardTitle>Run history</CardTitle>
              <CardDescription>Every run of this project, newest first.</CardDescription>
            </CardHeader>
            <CardContent>
              {runs.loading && !runs.data ? (
                <Skeleton className="h-40" />
              ) : runs.error ? (
                <Alert variant="destructive">{runs.error}</Alert>
              ) : !runs.data?.length ? (
                <EmptyState title="No runs yet" className="py-8" />
              ) : (
                <Table>
                  <THead>
                    <TR className="hover:bg-transparent">
                      <TH>Run</TH>
                      <TH>Status</TH>
                      <TH className="hidden sm:table-cell">Date</TH>
                      <TH className="hidden md:table-cell">Mode</TH>
                      <TH>Key KPIs</TH>
                      <TH className="hidden sm:table-cell">Checks</TH>
                      <TH className="text-right">
                        <span className="sr-only">Links</span>
                      </TH>
                    </TR>
                  </THead>
                  <TBody>
                    {runs.data.map((r) => (
                      <TR key={r.id}>
                        <TD className="font-medium">
                          #{r.id}
                          {r.pipeline_id !== id && (
                            <span className="block text-xs font-normal text-muted-foreground">{r.pipeline_id ? "other version" : "first run"}</span>
                          )}
                        </TD>
                        <TD>
                          <RunStatusBadge status={r.status} />
                        </TD>
                        <TD className="hidden whitespace-nowrap text-muted-foreground sm:table-cell">{formatDateTime(r.finished_at ?? r.started_at)}</TD>
                        <TD className="hidden md:table-cell">{modeLabel(r.mode)}</TD>
                        <TD>
                          <div className="flex max-w-72 flex-wrap gap-x-3 gap-y-0.5 text-xs">
                            {(r.kpis ?? []).slice(0, 3).map((k) => (
                              <span key={k.key} className="whitespace-nowrap" title={k.label}>
                                <span className="text-muted-foreground">{k.label}:</span>{" "}
                                <span className="font-medium tabular-nums">{formatValue(k.value, k.format, k.unit)}</span>
                              </span>
                            ))}
                            {!r.kpis?.length && <span className="text-muted-foreground">—</span>}
                          </div>
                        </TD>
                        <TD className="hidden sm:table-cell">
                          {r.sanity_json ? (
                            <Badge variant={SANITY_VARIANT[r.sanity_json.status]}>
                              {r.sanity_json.status} · {r.sanity_json.checks_passed}/{r.sanity_json.checks_run}
                            </Badge>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TD>
                        <TD className="text-right">
                          <div className="flex justify-end gap-1">
                            {r.status === "COMPLETED" && (
                              <Link
                                href={`/projects/${r.project_id}/dashboard?run=${r.id}`}
                                className={buttonVariants({ variant: "ghost", size: "icon" })}
                                aria-label={`Dashboard for run ${r.id}`}
                                title="Dashboard"
                              >
                                <LayoutDashboard />
                              </Link>
                            )}
                            {r.status === "FAILED" && r.contract_check_json?.ok === false && r.pipeline_id === id && (
                              <Button variant="ghost" size="sm" onClick={() => setActiveRun(r)}>
                                Fix
                              </Button>
                            )}
                            <Link
                              href={`/projects/${r.project_id}/run?run=${r.id}`}
                              className={buttonVariants({ variant: "ghost", size: "icon" })}
                              aria-label={`Logs for run ${r.id}`}
                              title="Logs"
                            >
                              <ScrollText />
                            </Link>
                          </div>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Expected data (contract)</CardTitle>
              <CardDescription>New uploads must match this shape. Column names can be mapped.</CardDescription>
            </CardHeader>
            <CardContent>
              {!pl.contract_json ? (
                <p className="text-sm text-muted-foreground">No data contract saved.</p>
              ) : (
                <div className="space-y-4 text-sm">
                  <div>
                    <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Files (in order)</h4>
                    <ol className="list-decimal space-y-0.5 pl-5">
                      {pl.contract_json.files.map((f) => (
                        <li key={f} className="truncate" title={f}>
                          {f}
                        </li>
                      ))}
                    </ol>
                  </div>
                  <div>
                    <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Columns ({pl.contract_json.columns.length})
                    </h4>
                    <ul className="max-h-80 space-y-1 overflow-auto">
                      {pl.contract_json.columns.map((c) => (
                        <li key={`${c.dataset_index}-${c.name}`} className="flex items-center justify-between gap-2 rounded px-1 py-0.5 hover:bg-muted/50">
                          <span className="min-w-0 truncate" title={c.source_column !== c.name ? `${c.source_column} → ${c.name}` : c.name}>
                            <code className="text-xs">{c.source_column}</code>
                          </span>
                          <Badge variant="secondary">{c.type}</Badge>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <p className="text-xs text-muted-foreground">At least {pl.contract_json.min_rows.toLocaleString()} rows.</p>
                </div>
              )}
            </CardContent>
          </Card>
          <Link href={`/projects/${pl.project_id}/dashboard`} className={buttonVariants({ variant: "outline", className: "w-full" })}>
            <ExternalLink /> Project dashboard
          </Link>
        </div>
      </div>

      <AutomapDialog
        open={automapOpen}
        onOpenChange={setAutomapOpen}
        mapping={automap}
        onChange={setAutomap}
        options={automapOptions}
        onRetry={() => void retry()}
        retrying={retrying}
      />
    </>
  );
}
