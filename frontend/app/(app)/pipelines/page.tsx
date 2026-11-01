"use client";
import Link from "next/link";
import { ArrowRight, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, PageHeader, PathBadge } from "@/components/layout/common";

export default function PipelinesPage() {
  const { data, error, loading } = useLoad(() => api.listPipelines(), []);
  return (
    <>
      <PageHeader
        title="Pipelines"
        description="Saved, reusable analyses. Upload new data of the same shape to refresh results, with a contract check first."
      />
      {error && (
        <Alert variant="destructive" title="Could not load pipelines" className="mb-4">
          {error}
        </Alert>
      )}
      {loading && !data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : data && data.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((p) => (
            <Link
              key={p.id}
              href={`/pipelines/${p.id}`}
              className="group flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-sm transition hover:border-primary/50 hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-2">
                <h2 className="line-clamp-2 font-medium" title={p.project_name}>
                  {p.project_name || `Project #${p.project_id}`}
                </h2>
                <PathBadge path={p.path} />
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="secondary">v{p.version}</Badge>
                <Badge variant="secondary">
                  {p.run_count} run{p.run_count === 1 ? "" : "s"}
                </Badge>
                {!p.active && <Badge variant="outline">inactive</Badge>}
                {p.contract_json && (
                  <Badge variant="outline">
                    {p.contract_json.files.length} file{p.contract_json.files.length === 1 ? "" : "s"} · {p.contract_json.columns.length} columns
                  </Badge>
                )}
              </div>
              <div className="mt-auto flex items-center justify-between text-xs text-muted-foreground">
                <span>Saved {formatDateTime(p.created_at)}</span>
                <ArrowRight className="size-4 transition group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden />
              </div>
            </Link>
          ))}
        </div>
      ) : (
        !error && (
          <EmptyState
            icon={Workflow}
            title="No pipelines yet"
            description="A pipeline is saved automatically after a project's first successful run."
            action={
              <Link href="/" className={buttonVariants({ variant: "outline" })}>
                Go to projects
              </Link>
            }
          />
        )
      )}
    </>
  );
}
