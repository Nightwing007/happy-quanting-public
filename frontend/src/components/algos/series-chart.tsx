"use client";

import { useEffect, useRef } from "react";
import { useTheme } from "next-themes";
import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type Time,
} from "lightweight-charts";
import { themeColors } from "@/components/trade/price-chart";
import { parseApiTime } from "@/lib/format";

export type ChartLine = {
  name: string;
  color: string;
  points: { at: string; value: number }[];
  /** Filled down from the line (the strategy's drawdown) instead of a bare line. */
  area?: boolean;
};

/** Daily curves are keyed by date, intraday ones by unix seconds; both are valid chart times. */
function chartTime(at: string, intraday: boolean): Time {
  if (intraday) return Math.floor(parseApiTime(at).getTime() / 1000) as Time;
  return parseApiTime(at).toISOString().slice(0, 10) as Time;
}

/** A line chart for the equity curve or the drawdown. Drawn again whenever its data or theme changes. */
export function SeriesChart({
  lines,
  intraday,
  format,
  className,
}: {
  lines: ChartLine[];
  intraday: boolean;
  format: (value: number) => string;
  className?: string;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const c = themeColors(dark);
    const chart = createChart(container, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: c.text },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border, timeVisible: intraday, secondsVisible: false },
      localization: { priceFormatter: format },
    });
    for (const line of lines) {
      const options = { color: line.color, lineWidth: 2 as const, priceLineVisible: false, title: "" };
      const series = line.area
        ? chart.addSeries(AreaSeries, {
            lineColor: line.color,
            topColor: "transparent",
            bottomColor: `${line.color}55`,
            lineWidth: 2,
            priceLineVisible: false,
          })
        : chart.addSeries(LineSeries, options);
      // Times must rise strictly: when two points land on the same day the later one stands.
      const data: { time: Time; value: number }[] = [];
      for (const p of line.points) {
        const time = chartTime(p.at, intraday);
        if (data.length && data[data.length - 1].time === time) data[data.length - 1].value = p.value;
        else data.push({ time, value: p.value });
      }
      series.setData(data);
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [lines, dark, intraday, format]);

  return <div ref={ref} className={className} />;
}
