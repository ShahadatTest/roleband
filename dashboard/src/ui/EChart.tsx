import { useEffect, useId, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { EChartsCoreOption, EChartsType } from "echarts/core";
import {
  sharedEchartChartUnavailable,
} from "../copy/gen/shared";
import { Msg } from "./Msg";

type ChartEventHandler = (params: unknown) => void;

interface Props {
  ariaLabel: string;
  className?: string;
  height?: number;
  onEvents?: Record<string, ChartEventHandler>;
  option: EChartsCoreOption;
  summary: string;
}

const css = (styles: CSSStyleDeclaration, name: string, fallback: string) =>
  styles.getPropertyValue(name).trim() || fallback;

const colorKey = (key: string) => key === "color" || key.endsWith("Color");

function resolveOptionColors(value: unknown, key = "", cache = new Map<string, string>()): unknown {
  if (typeof value === "string" && colorKey(key) && /^(var|color-mix)\(/.test(value)) {
    const cached = cache.get(value);
    if (cached) return cached;
    const probe = document.createElement("span");
    probe.style.color = value;
    probe.style.position = "absolute";
    probe.style.visibility = "hidden";
    document.body.appendChild(probe);
    const resolved = getComputedStyle(probe).color;
    probe.remove();
    cache.set(value, resolved);
    return resolved;
  }
  if (Array.isArray(value)) return value.map((item) => resolveOptionColors(item, key, cache));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([childKey, child]) => [
        childKey,
        resolveOptionColors(child, childKey, cache),
      ]),
    );
  }
  return value;
}

/* The chart themes from --app-* at :root, with the --app-data-* categorical
 * ramp for series, whatever scope its host sits in.
 *
 * The names are read as STRINGS, so no `var()` gate can see them, and an
 * unresolved custom property here does not fall back to another vocabulary:
 * it falls through to the hard-coded dark-theme literals below, which would
 * paint a light-theme chart in dark ink. Those literals are the last resort
 * only. */
function themed(option: EChartsCoreOption): EChartsCoreOption {
  const styles = getComputedStyle(document.documentElement);
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const text = css(styles, "--app-text", "#eef0f3");
  const muted = css(styles, "--app-text-muted", "#9a9da4");
  const border = css(styles, "--app-border", "rgba(230,233,240,.09)");
  const elevated = css(styles, "--app-surface-raised", "#141416");

  const baseTooltip = {
    trigger: "item",
    appendToBody: true,
    backgroundColor: elevated,
    borderColor: border,
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: text, fontSize: 11 },
    extraCssText: "border-radius:8px;box-shadow:0 12px 36px rgba(0,0,0,.28)",
  };
  const resolvedOption = resolveOptionColors(option) as EChartsCoreOption;
  const customTooltip = resolvedOption.tooltip && !Array.isArray(resolvedOption.tooltip)
    ? resolvedOption.tooltip
    : {};

  return {
    animation: !reduced,
    animationDuration: 420,
    animationDurationUpdate: 220,
    animationEasing: "cubicOut",
    backgroundColor: "transparent",
    color: [
      css(styles, "--app-data-1", "#7ef0b2"),
      css(styles, "--app-data-2", "#6fc9e6"),
      css(styles, "--app-data-3", "#f0a45c"),
      css(styles, "--app-data-4", "#ff8484"),
      muted,
    ],
    ...resolvedOption,
    // The wrapper owns one stable accessible name + concise figcaption summary.
    // ECharts' generated ARIA rewrites the host label after every setOption and
    // turns keyboard/test targeting into a moving dump of the full dataset.
    aria: { enabled: false },
    textStyle: {
      color: text,
      // Read the token that exists: an undeclared font token renders the OS
      // fallback instead of the bundled face.
      fontFamily: css(styles, "--app-font-sans", '"IBM Plex Sans", system-ui, sans-serif'),
      fontSize: 11,
      ...(resolvedOption.textStyle ?? {}),
    },
    tooltip: { ...baseTooltip, ...customTooltip },
  };
}

export function EChart({
  ariaLabel,
  className = "",
  height = 260,
  onEvents,
  option,
  summary,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const optionRef = useRef(option);
  const eventsRef = useRef(onEvents);
  const ariaLabelRef = useRef(ariaLabel);
  const summaryId = useId();
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  optionRef.current = option;
  eventsRef.current = onEvents;
  ariaLabelRef.current = ariaLabel;

  useEffect(() => {
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    let themeObserver: MutationObserver | null = null;
    let windowResize: (() => void) | null = null;

    const mount = async () => {
      try {
        if (
          hostRef.current?.clientWidth === 0 &&
          hostRef.current?.clientHeight === 0 &&
          typeof ResizeObserver === "undefined"
        ) return;
        const { echarts } = await import("./echartsRuntime");
        if (disposed || !hostRef.current) return;

        const chart = echarts.init(hostRef.current, undefined, { renderer: "svg" });
        chartRef.current = chart;
        chart.setOption(themed(optionRef.current), { notMerge: true });
        hostRef.current.setAttribute("aria-label", ariaLabelRef.current);
        setReady(true);

        for (const [event, handler] of Object.entries(eventsRef.current ?? {})) {
          (chart.on as (name: string, cb: ChartEventHandler) => void)(event, handler);
        }

        if (typeof ResizeObserver !== "undefined") {
          resizeObserver = new ResizeObserver(() => chart.resize());
          resizeObserver.observe(hostRef.current);
        } else {
          windowResize = () => chart.resize();
          window.addEventListener("resize", windowResize);
        }

        themeObserver = new MutationObserver(() => {
          chart.setOption(themed(optionRef.current), { notMerge: true });
          hostRef.current?.setAttribute("aria-label", ariaLabelRef.current);
        });
        themeObserver.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ["data-theme"],
        });
      } catch {
        if (!disposed) setFailed(true);
      }
    };

    void mount();
    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      themeObserver?.disconnect();
      if (windowResize) window.removeEventListener("resize", windowResize);
      if (chartRef.current) {
        chartRef.current.dispose();
        chartRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.setOption(themed(option), { notMerge: true });
    hostRef.current?.setAttribute("aria-label", ariaLabel);
  }, [ariaLabel, option]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    for (const event of Object.keys(eventsRef.current ?? {})) chart.off(event);
    for (const [event, handler] of Object.entries(onEvents ?? {})) {
      (chart.on as (name: string, cb: ChartEventHandler) => void)(event, handler);
    }
  }, [onEvents]);

  return (
    <figure
      className={/* not copy: class names */ `echart ${className}`.trim()}
      data-chart={ariaLabel}
      style={{ "--chart-height": `${height}px` } as CSSProperties}
    >
      <div
        ref={hostRef}
        className="echart-canvas"
        role="img"
        aria-label={ariaLabel}
        aria-describedby={summaryId}
        aria-busy={!ready && !failed}
      />
      <figcaption id={summaryId} className="sr-only">{summary}</figcaption>
      {!ready && !failed && <div className="echart-loading" aria-hidden="true"><span /></div>}
      {failed && <div className="echart-fallback"><Msg of={sharedEchartChartUnavailable} elems={{ summary: summary }} /></div>}
    </figure>
  );
}
