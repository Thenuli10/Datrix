"use client";
import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ExternalLink, LayoutDashboard, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { useIdParam, useLoad } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Alert } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { PageSkeleton, Skeleton } from "@/components/ui/skeleton";
import { EmptyState, PageHeader, ProjectSteps, RunStatusBadge } from "@/components/layout/common";
import { DashboardView, ResultsSummaryLine } from "@/components/dashboard/DashboardView";
import { RunCompare } from "@/components/dashboard/RunCompare";

function DashboardInner() {
  const id = useIdParam();
  const router = useRouter();
  const search = useSearchParams();
  const project = useLoad(() => api.getProject(id), [id]);
  const runs = useLoad(() => api.listProjectRuns(id), [id]);

  const completed = React.useMemo(() => (runs.data ?? []).filter((r) => r.status === "COMPLETED"), [runs.data]);
  const runParam = Number(search.get("run")) || null;
  const compareParam = Number(search.get("compare")) || null;
  const runId = runParam ?? completed[0]?.id ?? null;

  const dash = useLoad(() => (runId ? api.getDashboard(runId) : Promise.resolve(null)), [runId]);
  const cmp = useLoad(() => (compareParam ? api.getDashboard(compareParam) : Promise.resolve(null)), [compareParam]);

  const setParam = (key: "run" | "compare", value: string) => {
    const q = new URLSearchParams(search.toString());
    if (value) q.set(key, value);
    else q.delete(key);
    router.replace(`/projects/${id}/dashboard?${q.toString()}`);
  };

  if (project.loading && !project.data) return <PageSkeleton />;
  if (!project.data) return <Alert variant="destructive" title="Could not load project">{project.error}</Alert>;
  const p = project.data;
  const payload = dash.data;
  const runLabel = (rid: number) => {
    const r = runs.data?.find((x) => x.id === rid);
    return r ? `Run #${r.id} · ${formatDateTime(r.finished_at ?? r.started_at)}` : `Run #${rid}`;
  };

  return (
    <>
      <ProjectSteps projectId={id} status={p.status} current="dashboard" />
      <PageHeader
        eyebrow="Dashboard"
        title={payload?.spec?.title ?? payload?.results?.summary?.title ?? p.name}
        description={payload?.results ? <ResultsSummaryLine results={payload.results} /> : undefined}
        actions={
          <>
            {completed.length > 0 && (
              <>
                <label htmlFor="dash-run" className="sr-only">
                  Run to show
                </label>
                <Select id="dash-run" wrapperClassName="w-56" value={runId ?? ""} onChange={(e) => setParam("run", e.target.value)}>
                  {completed.map((r) => (
                    <option key={r.id} value={r.id}>
                      {runLabel(r.id)}
                    </option>
                  ))}
                </Select>
              </>
            )}
            {completed.length > 1 && (
              <>
                <label htmlFor="dash-compare" className="sr-only">
                  Compare with run
                </label>
                <Select id="dash-compare" wrapperClassName="w-52" value={compareParam ?? ""} onChange={(e) => setParam("compare", e.target.value)}>
                  <option value="">Compare with…</option>
                  {completed
                    .filter((r) => r.id !== runId)
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        {runLabel(r.id)}
                      </option>
                    ))}
                </Select>
              </>
            )}
            {p.pipeline_id && (
              <Link href={`/pipelines/${p.pipeline_id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
                <Upload /> New data
              </Link>
            )}
            {runId && (
              <Link
                href={`/render/runs/${runId}`}
                target="_blank"
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
                title="Open the print-friendly dashboard"
              >
                <ExternalLink /> <span className="sr-only sm:not-sr-only">Full page</span>
              </Link>
            )}
          </>
        }
      />

      {runs.error && <Alert variant="destructive" title="Could not load runs">{runs.error}</Alert>}
      {!runs.loading && !runId ? (
        <EmptyState
          icon={LayoutDashboard}
          title="No completed run yet"
          description={
            runs.data?.length
              ? `The latest run is ${runs.data[0].status.toLowerCase()}.`
              : "Approve a plan to produce the first dashboard."
          }
          action={
            runs.data?.length ? (
              <Link href={`/projects/${id}/run?run=${runs.data[0].id}`} className={buttonVariants()}>
                View run <RunStatusBadge status={runs.data[0].status} />
              </Link>
            ) : (
              <Link href={`/projects/${id}/plan`} className={buttonVariants()}>
                Go to plan
              </Link>
            )
          }
        />
      ) : dash.error ? (
        <Alert variant="destructive" title="Could not load dashboard">{dash.error}</Alert>
      ) : !payload ? (
        <div className="space-y-4" aria-busy="true" aria-label="Loading dashboard">
          <Skeleton className="h-12" />
          <div className="grid gap-4 md:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Skeleton className="h-72" />
            <Skeleton className="h-72" />
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {compareParam && cmp.data?.results && payload.results && (
            <RunCompare
              current={payload.results}
              previous={cmp.data.results}
              currentLabel={`Run #${runId}`}
              previousLabel={`Run #${compareParam}`}
            />
          )}
          <DashboardView key={runId} payload={payload} />
        </div>
      )}
    </>
  );
}

export default function DashboardPage() {
  return (
    <React.Suspense fallback={<PageSkeleton />}>
      <DashboardInner />
    </React.Suspense>
  );
}
