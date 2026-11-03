
export const SIGNAL = "var(--app-data-1)";
export const DATA_2 = "var(--app-data-2)";
export const WARN = "var(--app-data-3)";
export const DANGER = "var(--app-data-4)";
export const MUTED = "var(--app-text-muted)";
export const FAINT = "var(--app-text-faint)";
export const BORDER = "var(--app-border)";
export const SUNKEN = "var(--app-surface-sunken)";

export const compactGrid = {
  left: 8,
  right: 28,
  top: 18,
  bottom: 18,
  outerBoundsMode: "same" as const,
  outerBoundsContain: "axisLabel" as const,
};

export const categoryAxis = {
  type: "category" as const,
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: MUTED, fontSize: 11, overflow: "truncate", width: 112 },
};

export const valueAxis = {
  type: "value" as const,
  minInterval: 1,
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: FAINT, fontSize: 10 },
  splitLine: { lineStyle: { color: BORDER, type: "dashed" as const } },
};

