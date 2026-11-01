"use client";
import * as React from "react";
import Link from "next/link";
import { ArrowRight, FolderKanban, ImageOff, Plus, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/hooks";
import type { Project } from "@/lib/types";
import { formatDateTime, humanize } from "@/lib/format";
import { projectStepHref } from "@/lib/utils";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, PageHeader, ProjectStatusBadge } from "@/components/layout/common";

function Thumbnail({ runId }: { runId: number | null }) {
  const [failed, setFailed] = React.useState(false);
  if (!runId || failed) {
    return (
      <div className="flex aspect-[16/9] items-center justify-center bg-muted/60 text-muted-foreground">
        <ImageOff className="size-6 opacity-50" aria-hidden />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- served by the backend, size unknown
    <img
      src={api.thumbnailUrl(runId)}
      alt="Dashboard preview"
      loading="lazy"
      onError={() => setFailed(true)}
      className="aspect-[16/9] w-full object-cover object-top"
    />
  );
}

function ProjectCard({ p }: { p: Project }) {
  const href = projectStepHref(p);
  const showThumb = p.status === "COMPLETED" || p.status === "RERUNNING";
  return (
    <Link
      href={href}
      className="group flex flex-col overflow-hidden rounded-xl border bg-card shadow-sm transition hover:border-primary/50 hover:shadow-md"
    >
      {showThumb ? (
        <Thumbnail runId={p.latest_run_id} />
      ) : (
        <div className="flex aspect-[16/9] items-center justify-center bg-gradient-to-br from-primary/10 to-muted/40 px-6 text-center text-sm text-muted-foreground">
          {p.analysis?.summary ?? p.requirement_text}
        </div>
      )}
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <h2 className="line-clamp-2 font-medium leading-snug" title={p.name}>
            {p.name}
          </h2>
          <ProjectStatusBadge status={p.status} />
        </div>
        <div className="mt-auto flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {p.analysis?.task_type ? `${humanize(p.analysis.task_type)} · ` : ""}
            {formatDateTime(p.created_at)}
          </span>
          <ArrowRight className="size-4 transition group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden />
        </div>
      </div>
    </Link>
  );
}

export default function ProjectsPage() {
  const { data, error, loading, reload } = useLoad(() => api.listProjects(), []);
  return (
    <>
      <PageHeader
        title="Projects"
        description="Each project is one analysis goal. Describe what you want to learn, upload data, and get a reusable pipeline and dashboard."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => void reload()} aria-label="Refresh projects">
              <RefreshCw /> Refresh
            </Button>
            <Link href="/projects/new" className={buttonVariants({ size: "sm" })}>
              <Plus /> New project
            </Link>
          </>
        }
      />
      {error && (
        <Alert variant="destructive" title="Could not load projects" className="mb-4">
          {error}
        </Alert>
      )}
      {loading && !data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="overflow-hidden rounded-xl border bg-card">
              <Skeleton className="aspect-[16/9] rounded-none" />
              <div className="space-y-2 p-4">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            </div>
          ))}
        </div>
      ) : data && data.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((p) => (
            <ProjectCard key={p.id} p={p} />
          ))}
        </div>
      ) : (
        !error && (
          <EmptyState
            icon={FolderKanban}
            title="No projects yet"
            description="Start by describing what you want to learn from your data. Datrix will tell you what data it needs."
            action={
              <Link href="/projects/new" className={buttonVariants()}>
                <Plus /> Create your first project
              </Link>
            }
          />
        )
      )}
    </>
  );
}
