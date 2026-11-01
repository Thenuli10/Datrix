"use client";
import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, LayoutDashboard, PlayCircle } from "lucide-react";
import { api, errorMessage, streamLogs } from "@/lib/api";
import { useIdParam, useInterval, useLoad } from "@/lib/hooks";
import type { Run } from "@/lib/types";
import { formatDateTime, formatDuration } from "@/lib/format";
import { isRunActive } from "@/lib/utils";
import { Alert } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageSkeleton } from "@/components/ui/skeleton";
import { Select } from "@/components/ui/select";
import { EmptyState, PageHeader, ProjectSteps, RunStatusBadge } from "@/components/layout/common";
import { ContractCheckView, StageIndicator } from "@/components/run/RunProgress";
import { LogViewer } from "@/components/run/LogViewer";
import { DriftAlert } from "@/components/dashboard/DashboardView";

const MAX_LINES = 5000;

function useRunLogs(runId: number | null, active: boolean) {
  const [lines, setLines] = React.useState<string[]>([]);
  const [streaming, setStreaming] = React.useState(false);
  const activeRef = React.useRef(active);
  activeRef.current = active;

  React.useEffect(() => {
    if (!runId) return;
    setLines([]);
    let close: (() => void) | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    const open = () => {
      setStreaming(true);
      close = streamLogs(
        runId,
        (line) => setLines((ls) => (ls.length >= MAX_LINES ? [...ls.slice(-MAX_LINES + 1), line] : [...ls, line])),
        (err) => {
          setStreaming(false);
          // Connection dropped while the run is still going: reconnect.
          if (err && activeRef.current && !cancelled) retry = setTimeout(open, 3000);
        },
      );
    };
    open();
    return () => {
      cancelled = true;
      close?.();
      if (retry) clearTimeout(retry);
    };
  }, [runId]);

  return { lines, streaming };
}

function RunInner() {
  const id = useIdParam();
  const router = useRouter();
  const search = useSearchParams();
  const runParam = Number(search.get("run")) || null;

  const project = useLoad(() => api.getProject(id), [id]);
  const runs = useLoad(() => api.listProjectRuns(id), [id]);
  const runId = runParam ?? runs.data?.[0]?.id ?? null;

  const [run, setRun] = React.useState<Run | null>(null);
  const [runError, setRunError] = React.useState<string | null>(null);
  const redirected = React.useRef(false);

  const fetchRun = React.useCallback(async () => {
    if (!runId) return;
    try {
      const r = await api.getRun(runId);
      setRun(r);
      setRunError(null);
    } catch (e) {
      setRunError(errorMessage(e));
    }
  }, [runId]);

  React.useEffect(() => {
    setRun(null);
    redirected.current = false;
    void fetchRun();
  }, [fetchRun]);

  const active = isRunActive(run?.status ?? "QUEUED");
  useInterval(() => void fetchRun(), 2000, !!runId && active);
  const { lines, streaming } = useRunLogs(runId, active);

  // Auto-redirect to the dashboard when the run completes while we watch it.
  const wasActive = React.useRef(false);
  React.useEffect(() => {
    if (!run) return;
    if (isRunActive(run.status)) wasActive.current = true;
    if (run.status === "COMPLETED" && wasActive.current && !redirected.current) {
      redirected.current = true;
      const t = setTimeout(() => router.push(`/projects/${id}/dashboard?run=${run.id}`), 1500);
      return () => clearTimeout(t);
    }
  }, [run, id, router]);

  if (project.loading && !project.data) return <PageSkeleton />;
  if (!project.data) return <Alert variant="destructive" title="Could not load project">{project.error}</Alert>;
  const p = project.data;

  if (!runs.loading && !runId) {
    return (
      <>
        <ProjectSteps projectId={id} status={p.status} current="run" />
        <EmptyState
          icon={PlayCircle}
          title="No runs yet"
          description="Approve a plan to start the first run."
          action={
            <Link href={`/projects/${id}/plan`} className={buttonVariants()}>
              Go to plan
            </Link>
          }
        />
      </>
    );
  }

  const failed = run?.status === "FAILED";
  const completed = run?.status === "COMPLETED";

  return (
    <>
      <ProjectSteps projectId={id} status={p.status} current="run" />
      <PageHeader
        eyebrow="Step 4 · Run"
        title={p.name}
        description={
          run
            ? `Run #${run.id} · ${run.mode === "train" ? "train model" : run.mode} · started ${formatDateTime(run.started_at)} · ${formatDuration(run.started_at, run.finished_at)}`
            : "Loading run…"
        }
        actions={
          <>
            {runs.data && runs.data.length > 1 && (
              <>
                <label htmlFor="run-select" className="sr-only">
                  Choose run
                </label>
                <Select
                  id="run-select"
                  wrapperClassName="w-44"
                  value={runId ?? ""}
                  onChange={(e) => router.replace(`/projects/${id}/run?run=${e.target.value}`)}
                >
                  {runs.data.map((r) => (
                    <option key={r.id} value={r.id}>
                      Run #{r.id} · {r.status.toLowerCase()}
                    </option>
                  ))}
                </Select>
              </>
            )}
            {run && <RunStatusBadge status={run.status} />}
          </>
        }
      />

      {runError && (
        <Alert variant="destructive" title="Could not load run" className="mb-4">
          {runError}
        </Alert>
      )}

      {completed && (
        <Alert variant="success" title="Run completed" className="mb-4">
          <div className="flex flex-wrap items-center gap-3">
            <span>Opening the dashboard…</span>
            <Link href={`/projects/${id}/dashboard?run=${run.id}`} className={buttonVariants({ size: "sm" })}>
              <LayoutDashboard /> Open dashboard
            </Link>
          </div>
        </Alert>
      )}

      {failed && (
        <div className="mb-4 space-y-3">
          <Alert variant="destructive" title="Run failed">
            <p className="whitespace-pre-wrap break-words">{run.error || "The run stopped with an error. See the logs for details."}</p>
            <div className="mt-2 flex flex-wrap gap-3 text-sm">
              {run.pipeline_id ? (
                <Link className="underline" href={`/pipelines/${run.pipeline_id}`}>
                  Back to pipeline
                </Link>
              ) : (
                <>
                  <Link className="underline" href={`/projects/${id}/plan`}>
                    Review plan
                  </Link>
                  <Link className="underline" href={`/projects/${id}/data`}>
                    Check data
                  </Link>
                </>
              )}
            </div>
          </Alert>
          <ContractCheckView check={run.contract_check_json} compact />
        </div>
      )}
      {run?.drift_json && <div className="mb-4"><DriftAlert drift={run.drift_json} /></div>}

      <div className="grid gap-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-sm">Progress</CardTitle>
          </CardHeader>
          <CardContent>{run ? <StageIndicator run={run} /> : <div className="h-48 animate-pulse rounded bg-muted" />}</CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader className="flex-row items-center justify-between">
            <div className="space-y-1">
              <CardTitle className="text-sm">Logs</CardTitle>
              <CardDescription>{streaming ? "Live" : active ? "Reconnecting…" : "Finished"}</CardDescription>
            </div>
            {completed && (
              <Link href={`/projects/${id}/dashboard?run=${run.id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
                Dashboard <ArrowRight />
              </Link>
            )}
          </CardHeader>
          <CardContent>
            <LogViewer lines={lines} live={active} />
          </CardContent>
        </Card>
      </div>
    </>
  );
}

export default function RunPage() {
  return (
    <React.Suspense fallback={<PageSkeleton />}>
      <RunInner />
    </React.Suspense>
  );
}
