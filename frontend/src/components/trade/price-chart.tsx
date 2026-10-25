"use client";

import { useEffect, useRef } from "react";
import { useTheme } from "next-themes";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type AutoscaleInfo,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { priceDecimals, toNumber } from "@/lib/format";
import type { Bar, IndicatorSeries } from "@/lib/types";

export type ChartPriceLine = { price: number; color?: string; title?: string; dashed?: boolean };
export type ChartMarker = SeriesMarker<Time>;
export type HoverBar = { open: number; high: number; low: number; close: number; volume: number | null };

const UP = "#16a34a";
const DOWN = "#dc2626";

const INDICATOR_COLORS: Record<string, string> = {
  "sma:20": "#f59e0b",
  "sma:50": "#3b82f6",
  "ema:20": "#a855f7",
  "ema:50": "#ec4899",
  "rsi:14": "#0ea5e9",
};
const FALLBACK_COLORS = ["#14b8a6", "#f97316", "#84cc16", "#06b6d4"];

const indicatorKey = (i: IndicatorSeries) => `${i.name}:${i.period}`;

export function indicatorColor(i: IndicatorSeries, index = 0): string {
  return INDICATOR_COLORS[indicatorKey(i)] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

export function themeColors(dark: boolean) {
  return dark
    ? { text: "#aaa1bd", grid: "rgba(168,85,247,0.08)", border: "rgba(168,85,247,0.2)", cross: "#7e6a9c" }
    : { text: "#4d4560", grid: "rgba(18,14,28,0.07)", border: "rgba(18,14,28,0.18)", cross: "#8a8099" };
}

// Daily-and-longer bars carry "YYYY-MM-DD"; intraday bars carry unix seconds. Both are valid chart times.
const asTime = (t: string | number) => t as Time;

type Props = {
  bars: Bar[];
  indicators: IndicatorSeries[];
  intraday: boolean;
  markers?: ChartMarker[];
  priceLines?: ChartPriceLine[];
  /** Bars only ever grow at the end (a replay): append them instead of reloading and re-fitting. */
  incremental?: boolean;
  onHover?: (bar: HoverBar | null) => void;
  className?: string;
};

export function PriceChart({ bars, indicators, intraday, markers, priceLines, incremental, onHover, className }: Props) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const indicatorRefs = useRef(new Map<string, { series: ISeriesApi<"Line">; lines: IPriceLine[] }>());
  const userLinesRef = useRef<IPriceLine[]>([]);
  // The prices of the lines the autoscale must keep in view; read by the candle series' provider.
  const linePricesRef = useRef<number[]>([]);
  const shownBarsRef = useRef<Bar[]>([]);
  const hoverRef = useRef(onHover);
  useEffect(() => {
    hoverRef.current = onHover;
  });

  // Create the chart once; every later change updates it in place.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const colors = themeColors(false);
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: colors.text,
        panes: { separatorColor: colors.border },
      },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border, rightOffset: 5 },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      // A stop, target or entry line outside the candles' range would be drawn off screen. Widen
      // the scale to include every line, with a little room so the label is not on the edge.
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const base = original();
        const prices = linePricesRef.current;
        if (!base?.priceRange || prices.length === 0) return base;
        const lo = Math.min(base.priceRange.minValue, ...prices);
        const hi = Math.max(base.priceRange.maxValue, ...prices);
        const pad = (hi - lo) * 0.04;
        return {
          ...base,
          priceRange: {
            minValue: lo < base.priceRange.minValue ? lo - pad : base.priceRange.minValue,
            maxValue: hi > base.priceRange.maxValue ? hi + pad : base.priceRange.maxValue,
          },
        };
      },
    });
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    // Volume lives in the bottom fifth of the price pane.
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    chart.subscribeCrosshairMove((param) => {
      const c = param.seriesData.get(candles) as
        | { open: number; high: number; low: number; close: number }
        | undefined;
      if (!c || !param.time) {
        hoverRef.current?.(null);
        return;
      }
      const v = param.seriesData.get(volume) as { value: number } | undefined;
      hoverRef.current?.({ open: c.open, high: c.high, low: c.low, close: c.close, volume: v?.value ?? null });
    });

    chartRef.current = chart;
    candleRef.current = candles;
    volumeRef.current = volume;
    markersRef.current = createSeriesMarkers(candles, []);
    const indicatorMap = indicatorRefs.current;
    return () => {
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      markersRef.current = null;
      indicatorMap.clear();
      shownBarsRef.current = [];
      userLinesRef.current = [];
    };
  }, []);

  // Theme.
  useEffect(() => {
    const c = themeColors(dark);
    chartRef.current?.applyOptions({
      layout: { textColor: c.text, panes: { separatorColor: c.border } },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border },
      crosshair: {
        vertLine: { color: c.cross, labelBackgroundColor: c.cross },
        horzLine: { color: c.cross, labelBackgroundColor: c.cross },
      },
    });
  }, [dark]);

  useEffect(() => {
    chartRef.current?.applyOptions({ timeScale: { timeVisible: intraday, secondsVisible: false } });
  }, [intraday]);

  // Candles and volume.
  useEffect(() => {
    const candles = candleRef.current;
    const volume = volumeRef.current;
    if (!candles || !volume) return;
    const candle = (b: Bar) => ({
      time: asTime(b.time),
      open: toNumber(b.open),
      high: toNumber(b.high),
      low: toNumber(b.low),
      close: toNumber(b.close),
    });
    const vol = (b: Bar) => ({
      time: asTime(b.time),
      value: toNumber(b.volume),
      color: toNumber(b.close) >= toNumber(b.open) ? "rgba(22,163,74,0.3)" : "rgba(220,38,38,0.3)",
    });
    const shown = shownBarsRef.current;
    const prevLast = shown.length ? shown[shown.length - 1] : null;
    const from = incremental && prevLast ? bars.findIndex((b) => b.time === prevLast.time) : -1;
    shownBarsRef.current = bars;
    if (from >= 0) {
      // Re-sending the last shown bar covers one that was still forming; the rest are new.
      for (const b of bars.slice(from)) {
        candles.update(candle(b));
        volume.update(vol(b));
      }
      // The first bars of a replay would otherwise stay as wide as the first single bar was.
      if (bars.length <= 120) chartRef.current?.timeScale().fitContent();
      return;
    }
    candles.setData(bars.map(candle));
    volume.setData(bars.map(vol));
    const last = bars.length ? toNumber(bars[bars.length - 1].close) : 0;
    const precision = priceDecimals(last);
    candles.applyOptions({ priceFormat: { type: "price", precision, minMove: 1 / 10 ** precision } });
    chartRef.current?.timeScale().fitContent();
  }, [bars, incremental]);

  // Indicators: add/remove series as the selection changes, refresh data otherwise.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const map = indicatorRefs.current;
    const wanted = new Set(indicators.map(indicatorKey));
    for (const [key, entry] of map) {
      if (!wanted.has(key)) {
        chart.removeSeries(entry.series);
        map.delete(key);
      }
    }
    indicators.forEach((ind, idx) => {
      const key = indicatorKey(ind);
      let entry = map.get(key);
      if (!entry) {
        const own = ind.pane === "own";
        const series = chart.addSeries(
          LineSeries,
          {
            color: indicatorColor(ind, idx),
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: own,
            crosshairMarkerVisible: false,
            title: own ? ind.label : "",
            ...(own
              ? {
                  // Pinned so the 70/30 lines stay visible whatever the data does.
                  autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
                  priceFormat: { type: "price" as const, precision: 1, minMove: 0.1 },
                }
              : {}),
          },
          own ? 1 : 0,
        );
        const lines = own
          ? [70, 30].map((price) =>
              series.createPriceLine({
                price,
                color: "rgba(113,113,122,0.8)",
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: true,
                title: "",
              }),
            )
          : [];
        entry = { series, lines };
        map.set(key, entry);
        if (own) chart.panes()[1]?.setStretchFactor(0.6);
      }
      entry.series.setData(ind.points.map((p) => ({ time: asTime(p.time), value: p.value })));
    });
  }, [indicators]);

  useEffect(() => {
    markersRef.current?.setMarkers(markers ?? []);
  }, [markers]);

  useEffect(() => {
    const candles = candleRef.current;
    if (!candles) return;
    for (const l of userLinesRef.current) candles.removePriceLine(l);
    linePricesRef.current = (priceLines ?? []).map((l) => l.price).filter(Number.isFinite);
    userLinesRef.current = (priceLines ?? []).map((l) =>
      candles.createPriceLine({
        price: l.price,
        color: l.color ?? "#71717a",
        lineWidth: 1,
        lineStyle: l.dashed === false ? LineStyle.Solid : LineStyle.Dashed,
        axisLabelVisible: true,
        title: l.title ?? "",
      }),
    );
    // Autoscale only re-asks the provider when something changes; the lines are not data.
    chartRef.current?.priceScale("right").applyOptions({ autoScale: true });
  }, [priceLines]);

  return <div ref={containerRef} className={className} />;
}
