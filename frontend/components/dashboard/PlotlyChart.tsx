"use client";
import * as React from "react";
import dynamic from "next/dynamic";
import type { Config, Data, Layout } from "plotly.js";
import type { PlotParams } from "react-plotly.js";
import { Skeleton } from "@/components/ui/skeleton";
import { useIsDark } from "@/components/layout/theme";
import { baseLayout, chartTheme, mergeLayout, type ChartTheme } from "./theme";

/** react-plotly.js bound to the minified Plotly bundle; client-only. */
const Plot = dynamic<PlotParams>(
  async () => {
    const [plotlyMod, factoryMod] = await Promise.all([
      import("plotly.js-dist-min"),
      import("react-plotly.js/factory"),
    ]);
    const Plotly = (plotlyMod as unknown as { default?: object }).default ?? plotlyMod;
    const factory = (factoryMod as unknown as { default: (p: object) => React.ComponentType<PlotParams> }).default;
    return factory(Plotly);
  },
  { ssr: false, loading: () => <Skeleton className="h-full w-full" /> },
);

const CONFIG: Partial<Config> = {
  responsive: true,
  displaylogo: false,
  displayModeBar: "hover",
  modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"],
  toImageButtonOptions: { format: "png", scale: 2 },
};

export interface PlotlyChartProps {
  /** Build traces/layout from the active theme so colours follow light/dark mode. */
  build: (t: ChartTheme) => { data: Data[]; layout?: Partial<Layout> };
  onReady?: () => void;
  ariaLabel?: string;
}

export function PlotlyChart({ build, onReady, ariaLabel }: PlotlyChartProps) {
  const dark = useIsDark();
  const theme = React.useMemo(() => chartTheme(dark), [dark]);
  const { data, layout } = React.useMemo(() => build(theme), [build, theme]);
  const fullLayout = React.useMemo(() => mergeLayout(baseLayout(theme), layout), [theme, layout]);
  const readyRef = React.useRef(false);
  const fire = React.useCallback(() => {
    if (readyRef.current) return;
    readyRef.current = true;
    onReady?.();
  }, [onReady]);

  return (
    <div className="h-full w-full min-h-0" role="figure" aria-label={ariaLabel}>
      <Plot
        data={data}
        layout={fullLayout}
        config={CONFIG}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
        onInitialized={fire}
        onUpdate={fire}
        onError={fire}
      />
    </div>
  );
}
