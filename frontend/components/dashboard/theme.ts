import type { Layout } from "plotly.js";

/**
 * Categorical palette (Observable 10): distinguishable for common colour-vision deficiencies
 * and readable on both the light and dark card backgrounds.
 */
export const PALETTE = [
  "#4269d0",
  "#efb118",
  "#ff725c",
  "#6cc5b0",
  "#3ca951",
  "#ff8ab7",
  "#a463f2",
  "#97bbf5",
  "#9c6b4e",
  "#9498a0",
];

/** Slightly brighter blue in dark mode for the primary series. */
export function paletteFor(dark: boolean): string[] {
  return dark ? ["#6f8ff0", ...PALETTE.slice(1)] : PALETTE;
}

export const OTHER_COLOR = "#9498a0";

export function sequentialScale(dark: boolean): [number, string][] {
  return dark
    ? [
        [0, "#16203a"],
        [0.25, "#24396e"],
        [0.5, "#3557a8"],
        [0.75, "#5d82e0"],
        [1, "#a9bfff"],
      ]
    : [
        [0, "#f1f5ff"],
        [0.25, "#c9d7fb"],
        [0.5, "#8ea8ef"],
        [0.75, "#4f73d9"],
        [1, "#1f3f9a"],
      ];
}

export function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

export interface ChartTheme {
  dark: boolean;
  text: string;
  muted: string;
  grid: string;
  line: string;
  hoverBg: string;
  palette: string[];
}

export function chartTheme(dark: boolean): ChartTheme {
  return dark
    ? {
        dark,
        text: "#e6e9f2",
        muted: "#a4adc2",
        grid: "rgba(164,173,194,0.16)",
        line: "rgba(164,173,194,0.35)",
        hoverBg: "#1a2338",
        palette: paletteFor(true),
      }
    : {
        dark,
        text: "#0f172a",
        muted: "#475569",
        grid: "rgba(71,85,105,0.14)",
        line: "rgba(71,85,105,0.35)",
        hoverBg: "#ffffff",
        palette: paletteFor(false),
      };
}

export const FONT_FAMILY =
  'var(--font-geist-sans), ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

/** Base Plotly layout: transparent background, min font 11px, auto margins for long tick labels. */
export function baseLayout(t: ChartTheme): Partial<Layout> {
  const axis = {
    automargin: true,
    gridcolor: t.grid,
    linecolor: t.line,
    zerolinecolor: t.line,
    tickfont: { size: 11, color: t.muted },
    title: { font: { size: 12, color: t.muted } },
    showline: false,
    ticks: "" as const,
  };
  return {
    autosize: true,
    margin: { l: 8, r: 12, t: 8, b: 8, pad: 2 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: FONT_FAMILY, size: 12, color: t.text },
    colorway: t.palette,
    xaxis: { ...axis },
    yaxis: { ...axis },
    legend: {
      orientation: "h",
      x: 0,
      y: 1.02,
      xanchor: "left",
      yanchor: "bottom",
      font: { size: 11, color: t.muted },
      bgcolor: "rgba(0,0,0,0)",
    },
    hoverlabel: {
      bgcolor: t.hoverBg,
      bordercolor: t.line,
      font: { family: FONT_FAMILY, size: 12, color: t.text },
    },
    hovermode: "closest",
  };
}

type AnyRecord = Record<string, unknown>;
const isObj = (v: unknown): v is AnyRecord => !!v && typeof v === "object" && !Array.isArray(v);

/** Deep-merge plain objects (arrays are replaced). */
export function mergeLayout<T extends object>(base: T, ...overrides: (Partial<T> | undefined)[]): T {
  const out: AnyRecord = { ...(base as AnyRecord) };
  for (const o of overrides) {
    if (!o) continue;
    for (const [k, v] of Object.entries(o)) {
      out[k] = isObj(v) && isObj(out[k]) ? mergeLayout(out[k] as AnyRecord, v as AnyRecord) : v;
    }
  }
  return out as T;
}
