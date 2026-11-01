/** Shared number / date formatters for KPIs, tables and chart hovers. */
import type { Format } from "./types";

const ISO_CURRENCY = /^[A-Z]{3}$/;
const CURRENCY_SYMBOLS: Record<string, string> = { $: "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR" };

function currencyCode(unit?: string | null): string | null {
  if (!unit) return null;
  const u = unit.trim();
  if (ISO_CURRENCY.test(u)) return u;
  return CURRENCY_SYMBOLS[u] ?? null;
}

export function toNumber(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

export function formatDate(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const d = new Date(typeof v === "number" ? v : String(v));
  if (Number.isNaN(d.getTime())) return String(v);
  const s = String(v);
  const hasTime = /T\d{2}:\d{2}/.test(s) && !/T00:00(:00)?/.test(s);
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(hasTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

/**
 * Format a value. `percent` expects a fraction (0.12 → "12.0%"), matching results.json §7.
 * `unit` is appended (or used as currency code / symbol for `currency`).
 */
export function formatValue(value: unknown, format: Format | null | undefined = "number", unit?: string | null): string {
  if (value === null || value === undefined || value === "") return "—";
  const fmt = format ?? "number";
  if (fmt === "date") return formatDate(value);
  if (fmt === "text") return unit ? `${value} ${unit}` : String(value);

  const n = toNumber(value);
  if (n === null) return String(value);

  let out: string;
  switch (fmt) {
    case "percent": {
      const pct = n * 100;
      const digits = Math.abs(pct) >= 100 ? 0 : 1;
      out = `${pct.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}%`;
      return out;
    }
    case "currency": {
      const code = currencyCode(unit) ?? "USD";
      const compact = Math.abs(n) >= 1e6;
      try {
        return new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: code,
          notation: compact ? "compact" : "standard",
          maximumFractionDigits: compact ? 1 : Math.abs(n) >= 1000 ? 0 : 2,
        }).format(n);
      } catch {
        return `${unit ?? "$"}${n.toLocaleString()}`;
      }
    }
    case "compact":
      out = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
      break;
    case "integer":
      out = Math.round(n).toLocaleString();
      break;
    default: {
      const abs = Math.abs(n);
      const digits = abs === 0 ? 0 : abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 1 ? 2 : 3;
      out = abs >= 1e7 ? new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n)
        : n.toLocaleString(undefined, { maximumFractionDigits: digits });
    }
  }
  return unit ? `${out} ${unit}` : out;
}

/** d3-format string for Plotly axes / hovers. */
export function plotlyTickFormat(format: Format | null | undefined): string | undefined {
  switch (format) {
    case "percent":
      return ".1~%";
    case "currency":
      return "$~s";
    case "compact":
      return "~s";
    case "integer":
      return ",d";
    case "number":
      return ",.4~g";
    default:
      return undefined;
  }
}

export function plotlyHoverFormat(format: Format | null | undefined): string | undefined {
  switch (format) {
    case "percent":
      return ".1%";
    case "currency":
      return "$,.2f";
    case "compact":
      return ".3~s";
    case "integer":
      return ",d";
    case "number":
      return ",.4~g";
    default:
      return undefined;
  }
}

export function truncate(s: string, max = 20): string {
  return s.length > max ? `${s.slice(0, Math.max(1, max - 1))}…` : s;
}

export function formatPct(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function formatDateTime(v: string | null | undefined): string {
  if (!v) return "—";
  // Backend timestamps are UTC; add Z if missing so they display in local time.
  const s = /[zZ]|[+-]\d{2}:?\d{2}$/.test(v) ? v : `${v}Z`;
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return "—";
  const fix = (v: string) => (/[zZ]|[+-]\d{2}:?\d{2}$/.test(v) ? v : `${v}Z`);
  const a = new Date(fix(start)).getTime();
  const b = end ? new Date(fix(end)).getTime() : Date.now();
  if (!Number.isFinite(a) || !Number.isFinite(b)) return "—";
  const s = Math.max(0, Math.round((b - a) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
