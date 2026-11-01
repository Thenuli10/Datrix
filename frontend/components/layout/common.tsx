"use client";
import * as React from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check } from "lucide-react";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { cn, PROJECT_STATUS_LABEL } from "@/lib/utils";
import type { ProjectStatus, RunStatus } from "@/lib/types";

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0 space-y-1">
        {eyebrow && <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight break-words">{title}</h1>
        {description && <div className="max-w-3xl text-sm text-muted-foreground">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center",
        className,
      )}
    >
      {Icon && (
        <div className="flex size-11 items-center justify-center rounded-full bg-muted">
          <Icon className="size-5 text-muted-foreground" />
        </div>
      )}
      <div className="space-y-1">
        <h2 className="font-medium">{title}</h2>
        {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}

const PROJECT_VARIANT: Record<ProjectStatus, BadgeProps["variant"]> = {
  DRAFT: "secondary",
  REQUIREMENTS_READY: "info",
  DATA_UPLOADED: "info",
  DATA_VALIDATED: "info",
  PLAN_PROPOSED: "default",
  PLAN_APPROVED: "default",
  RUNNING: "warning",
  RERUNNING: "warning",
  COMPLETED: "success",
  FAILED: "destructive",
};

export function ProjectStatusBadge({ status }: { status: ProjectStatus }) {
  return <Badge variant={PROJECT_VARIANT[status] ?? "secondary"}>{PROJECT_STATUS_LABEL[status] ?? status}</Badge>;
}

const RUN_VARIANT: Record<RunStatus, BadgeProps["variant"]> = {
  QUEUED: "secondary",
  RUNNING: "warning",
  CHECKING: "info",
  COMPLETED: "success",
  FAILED: "destructive",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const active = status === "RUNNING" || status === "CHECKING" || status === "QUEUED";
  return (
    <Badge variant={RUN_VARIANT[status] ?? "secondary"}>
      {active && <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-current" />}
      {status.charAt(0) + status.slice(1).toLowerCase()}
    </Badge>
  );
}

export function PathBadge({ path }: { path: "ml" | "script" }) {
  return <Badge variant={path === "ml" ? "default" : "info"}>{path === "ml" ? "ML model" : "Script"}</Badge>;
}

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose-dx", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

const STEPS = [
  { key: "requirement", label: "Requirement", href: (id: number) => `/projects/new?project=${id}` },
  { key: "data", label: "Data", href: (id: number) => `/projects/${id}/data` },
  { key: "plan", label: "Plan", href: (id: number) => `/projects/${id}/plan` },
  { key: "run", label: "Run", href: (id: number) => `/projects/${id}/run` },
  { key: "dashboard", label: "Dashboard", href: (id: number) => `/projects/${id}/dashboard` },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];

function reachedIndex(status: ProjectStatus): number {
  switch (status) {
    case "DRAFT":
      return 0;
    case "REQUIREMENTS_READY":
    case "DATA_UPLOADED":
      return 1;
    case "DATA_VALIDATED":
    case "PLAN_PROPOSED":
      return 2;
    case "PLAN_APPROVED":
    case "RUNNING":
    case "FAILED":
      return 3;
    case "COMPLETED":
    case "RERUNNING":
      return 4;
  }
}

/** Workflow stepper shown at the top of each project page. */
export function ProjectSteps({ projectId, status, current }: { projectId: number; status: ProjectStatus; current: StepKey }) {
  const reached = reachedIndex(status);
  return (
    <nav aria-label="Project steps" className="mb-6 overflow-x-auto">
      <ol className="flex min-w-max items-center gap-1 text-sm">
        {STEPS.map((s, i) => {
          const isCurrent = s.key === current;
          const done = i < reached && !isCurrent;
          const enabled = i <= reached;
          const content = (
            <span
              className={cn(
                "flex items-center gap-2 rounded-full px-3 py-1.5",
                isCurrent && "bg-primary/12 font-medium text-primary",
                !isCurrent && enabled && "text-foreground hover:bg-muted",
                !enabled && "text-muted-foreground",
              )}
            >
              <span
                className={cn(
                  "flex size-5 items-center justify-center rounded-full border text-[11px]",
                  isCurrent && "border-primary bg-primary text-primary-foreground",
                  done && "border-success bg-success text-white dark:text-background",
                )}
              >
                {done ? <Check className="size-3" aria-hidden /> : i + 1}
              </span>
              {s.label}
            </span>
          );
          return (
            <li key={s.key} className="flex items-center gap-1">
              {i > 0 && <span aria-hidden className="h-px w-4 bg-border sm:w-8" />}
              {enabled ? (
                <Link href={s.href(projectId)} aria-current={isCurrent ? "step" : undefined} className="rounded-full">
                  {content}
                </Link>
              ) : (
                <span aria-disabled="true">{content}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
