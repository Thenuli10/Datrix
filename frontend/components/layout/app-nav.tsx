"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Database, FolderKanban, Plus, Workflow } from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./theme";

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
