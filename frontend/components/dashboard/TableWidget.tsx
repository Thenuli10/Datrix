"use client";
import * as React from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3, Search } from "lucide-react";
import { formatValue, toNumber } from "@/lib/format";
import type { Format, Table, Widget } from "@/lib/types";
import { cn } from "@/lib/utils";
import { resolvedToTable, type Resolved } from "./resolve";
import { WidgetEmpty } from "./WidgetEmpty";

const PAGE_SIZE = 10;

function cellFormat(table: Table, col: string, rows: unknown[][], idx: number): Format {
  const f = table.column_formats?.[col];
  if (f) return f;
  const sample = rows.slice(0, 20).map((r) => r[idx]);
  return sample.every((v) => v === null || v === undefined || toNumber(v) !== null) ? "number" : "text";
}

function compare(a: unknown, b: unknown): number {
  const na = toNumber(a);
  const nb = toNumber(b);
  if (na !== null && nb !== null) return na - nb;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

export function TableWidget({ widget, resolved, onReady }: { widget: Widget; resolved: Resolved; onReady: () => void }) {
  React.useEffect(() => onReady(), [onReady]);
  const table = React.useMemo(() => resolvedToTable(resolved), [resolved]);
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<{ col: number; dir: 1 | -1 } | null>(null);
  const [page, setPage] = React.useState(0);
  const [hidden, setHidden] = React.useState<Set<string>>(() => new Set(widget.hidden_columns ?? []));
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const pickerRef = React.useRef<HTMLDivElement>(null);
  const searchId = React.useId();

  React.useEffect(() => setHidden(new Set(widget.hidden_columns ?? [])), [widget.hidden_columns]);
  React.useEffect(() => setPage(0), [query, sort, table]);
  React.useEffect(() => {
    if (!pickerOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (!pickerRef.current?.contains(e.target as Node)) setPickerOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPickerOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [pickerOpen]);

  const rows = React.useMemo(() => {
    if (!table) return [];
    const q = query.trim().toLowerCase();
    let out = q ? table.rows.filter((r) => r.some((v) => String(v ?? "").toLowerCase().includes(q))) : table.rows;
    if (sort) out = [...out].sort((a, b) => compare(a[sort.col], b[sort.col]) * sort.dir);
    return out;
  }, [table, query, sort]);

  if (!table || !table.columns.length) return <WidgetEmpty />;

  const visible = table.columns.map((c, i) => ({ c, i })).filter(({ c }) => !hidden.has(c));
  const formats = table.columns.map((c, i) => cellFormat(table, c, table.rows, i));
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows = rows.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const isNum = (f: Format) => f !== "text" && f !== "date";

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <label htmlFor={searchId} className="sr-only">
            Search {widget.title}
          </label>
          <Search aria-hidden className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            id={searchId}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search…"
            className="h-8 w-full rounded-md border border-input bg-card pl-7 pr-2 text-xs focus-visible:outline-2 focus-visible:outline-ring"
          />
        </div>
        {table.columns.length > 1 && (
          <div className="relative" ref={pickerRef}>
            <button
              type="button"
              onClick={() => setPickerOpen((o) => !o)}
              aria-expanded={pickerOpen}
              aria-haspopup="true"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-input bg-card px-2 text-xs hover:bg-muted"
            >
              <Columns3 className="size-3.5" aria-hidden />
              <span>Columns</span>
              {hidden.size > 0 && <span className="text-muted-foreground">({hidden.size} hidden)</span>}
            </button>
            {pickerOpen && (
              <div className="absolute right-0 z-20 mt-1 max-h-64 w-56 overflow-auto rounded-md border bg-card p-1 shadow-lg">
                {table.columns.map((c) => (
                  <label key={c} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted">
                    <input
                      type="checkbox"
                      checked={!hidden.has(c)}
                      onChange={(e) =>
                        setHidden((h) => {
                          const n = new Set(h);
                          if (e.target.checked) n.delete(c);
                          else if (table.columns.length - n.size > 1) n.add(c);
                          return n;
                        })
                      }
                      className="accent-[var(--primary)]"
                    />
                    <span className="truncate" title={c}>
                      {c}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted">
            <tr>
              {visible.map(({ c, i }) => {
                const active = sort?.col === i;
                return (
                  <th
                    key={c}
                    scope="col"
                    aria-sort={active ? (sort!.dir === 1 ? "ascending" : "descending") : "none"}
                    className={cn("px-2.5 py-2 font-medium text-muted-foreground", isNum(formats[i]) ? "text-right" : "text-left")}
                  >
                    <button
                      type="button"
                      onClick={() =>
                        setSort((s) => (s?.col === i ? (s.dir === 1 ? { col: i, dir: -1 } : null) : { col: i, dir: 1 }))
                      }
                      className={cn(
                        "inline-flex max-w-48 items-center gap-1 rounded hover:text-foreground",
                        isNum(formats[i]) && "flex-row-reverse",
                      )}
                      title={`Sort by ${c}`}
                    >
                      <span className="truncate">{c}</span>
                      {active && (sort!.dir === 1 ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />)}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr>
                <td colSpan={visible.length} className="px-3 py-6 text-center text-muted-foreground">
                  {query ? "No rows match your search." : "No rows."}
                </td>
              </tr>
            ) : (
              pageRows.map((r, ri) => (
                <tr key={ri} className="border-t hover:bg-muted/50">
                  {visible.map(({ c, i }) => {
                    const text = formatValue(r[i], formats[i]);
                    return (
                      <td
                        key={c}
                        className={cn("max-w-64 truncate px-2.5 py-1.5", isNum(formats[i]) ? "text-right tabular-nums" : "text-left")}
                        title={String(r[i] ?? "")}
                      >
                        {text}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {rows.length.toLocaleString()} row{rows.length === 1 ? "" : "s"}
          {query && ` (of ${table.rows.length.toLocaleString()})`}
        </span>
        {pages > 1 && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Previous page"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="rounded p-1 hover:bg-muted disabled:opacity-40"
            >
              <ChevronLeft className="size-4" />
            </button>
            <span className="tabular-nums">
              {page + 1} / {pages}
            </span>
            <button
              type="button"
              aria-label="Next page"
              disabled={page >= pages - 1}
              onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
              className="rounded p-1 hover:bg-muted disabled:opacity-40"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
