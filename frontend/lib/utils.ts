import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Project } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** The page a project should open on, based on its workflow status. */
export function projectStepHref(p: Pick<Project, "id" | "status" | "latest_run_id" | "pipeline_id">): string {
  switch (p.status) {
    case "DRAFT":
      return `/projects/new?project=${p.id}`;
    case "REQUIREMENTS_READY":
    case "DATA_UPLOADED":
      return `/projects/${p.id}/data`;
    case "DATA_VALIDATED":
    case "PLAN_PROPOSED":
      return `/projects/${p.id}/plan`;
    case "PLAN_APPROVED":
    case "RUNNING":
    case "FAILED":
      return `/projects/${p.id}/run${p.latest_run_id ? `?run=${p.latest_run_id}` : ""}`;
    case "RERUNNING":
      return p.pipeline_id ? `/pipelines/${p.pipeline_id}` : `/projects/${p.id}/run`;
    case "COMPLETED":
      return `/projects/${p.id}/dashboard`;
    default:
      return `/projects/${p.id}/data`;
  }
}

export const PROJECT_STATUS_LABEL: Record<string, string> = {
  DRAFT: "Clarifying",
  REQUIREMENTS_READY: "Needs data",
  DATA_UPLOADED: "Data uploaded",
  DATA_VALIDATED: "Data validated",
  PLAN_PROPOSED: "Plan ready",
  PLAN_APPROVED: "Plan approved",
  RUNNING: "Running",
  COMPLETED: "Completed",
  FAILED: "Failed",
  RERUNNING: "Re-running",
};

export function isRunActive(status: string | null | undefined): boolean {
  return status === "QUEUED" || status === "RUNNING" || status === "CHECKING";
}
