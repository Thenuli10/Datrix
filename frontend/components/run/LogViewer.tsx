"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

function lineClass(line: string): string {
  if (/::error::|Traceback|Error\b|FAILED/i.test(line)) return "text-red-500 dark:text-red-400";
  if (/warn/i.test(line)) return "text-amber-600 dark:text-amber-400";
  if (/^\s*(✓|OK|PASS|Completed)/i.test(line)) return "text-emerald-600 dark:text-emerald-400";
  return "";
}

/** Live log output; sticks to the bottom unless the user scrolls up. */
export function LogViewer({ lines, live, className }: { lines: string[]; live: boolean; className?: string }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const stick = React.useRef(true);
  React.useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [lines]);
  return (
    <div
      ref={ref}
      role="log"
      aria-live="polite"
      aria-label="Run logs"
      tabIndex={0}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      }}
      className={cn(
        "h-[28rem] overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-relaxed",
        className,
      )}
    >
      {lines.length === 0 ? (
        <div className="text-muted-foreground">{live ? "Waiting for output…" : "No log output."}</div>
      ) : (
        lines.map((l, i) => (
          <div key={i} className={cn("whitespace-pre-wrap break-words", lineClass(l))}>
            {l || " "}
          </div>
        ))
      )}
      {live && lines.length > 0 && <div aria-hidden className="mt-1 inline-block h-3 w-1.5 animate-pulse bg-foreground/50" />}
    </div>
  );
}
