"use client";
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Database, FolderKanban, Plus, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import type { Usage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./theme";

/** "OpenAI today: $0.12 / $3.00" — refreshed on navigation (GET only, no LLM calls). */
function UsageBadge({ pathname }: { pathname: string }) {
  const [usage, setUsage] = React.useState<Usage | null>(null);
  React.useEffect(() => {
    let live = true;
    api
      .getUsage()
      .then((u) => live && setUsage(u))
      .catch(() => live && setUsage(null));
    return () => {
      live = false;
    };
  }, [pathname]);
  if (!usage) return null;
  const { cost_usd } = usage.today;
  const limit = usage.limits.daily_budget_usd;
  const near = limit > 0 && cost_usd >= 0.8 * limit;
  return (
    <span
      className={cn("mr-2 hidden text-xs tabular-nums text-muted-foreground md:inline", near && "font-medium text-destructive")}
      title={
        usage.fake
          ? "Offline mode (fake LLM): no OpenAI calls are made."
          : `Estimated spend. Caps: $${usage.limits.max_cost_per_run_usd.toFixed(2)}/run, ` +
            `$${usage.limits.max_cost_per_project_usd.toFixed(2)}/project, ` +
            `${usage.limits.max_calls_per_project} calls/project (backend/.env).`
      }
    >
      {usage.fake ? "OpenAI: offline" : `OpenAI today: $${cost_usd.toFixed(2)} / $${limit.toFixed(2)}`}
    </span>
  );
}

const LINKS = [
  { href: "/", label: "Projects", icon: FolderKanban, match: (p: string) => p === "/" || p.startsWith("/projects") },
  { href: "/pipelines", label: "Pipelines", icon: Workflow, match: (p: string) => p.startsWith("/pipelines") },
];

export function AppNav() {
  const pathname = usePathname() ?? "/";
  return (
    <header className="sticky top-0 z-40 border-b bg-card/85 backdrop-blur supports-[backdrop-filter]:bg-card/70">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4 sm:gap-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 rounded-md font-semibold tracking-tight">
          <span className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Database className="size-4" aria-hidden />
          </span>
          <span className="hidden sm:inline">Datrix</span>
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1">
          {LINKS.map(({ href, label, icon: Icon, match }) => {
            const active = match(pathname);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                  active && "bg-muted text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <UsageBadge pathname={pathname} />
          <Link
            href="/projects/new"
            className="hidden h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90 sm:inline-flex"
          >
            <Plus className="size-4" aria-hidden /> New project
          </Link>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
