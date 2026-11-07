export type ChatChartType =
  | "bar"
  | "line"
  | "area"
  | "stacked_bar"
  | "donut"
  | "pie"
  | "ranking"
  | "scatter"
  | "bubble"
  | "heatmap"
  | "radar"
  | "funnel"
  | "gauge"
  | "treemap"
  | "histogram"
  | "kpi";

export interface ChatChartSeries {
  key: string;
  label: string;
  format?: ChatKpiFormat;
}

export interface ChatChartRow {
  label: string;
  [key: string]: string | number | null | undefined;
}

export type ChatKpiFormat =
  | "number"
  | "currency"
  | "percent"
  | "rating"
  | "seconds"
  | "ratio"
  | "text";

export interface ChatChartKpi {
  label: string;
  value: number | string | null;
  format?: ChatKpiFormat;
  delta?: number | null;
}

export interface ChatChart {
  id: string;
  type: ChatChartType;
  title: string;
  subtitle?: string | null;
  dataset?: string | null;
  domain?: string | null;
  x_label?: string | null;
  y_label?: string | null;
  series: ChatChartSeries[];
  rows: ChatChartRow[];
  kpis?: ChatChartKpi[];
  window_days?: number | null;
  /** Heatmap axis order, supplied by the backend (hours / weekdays). */
  x_values?: string[] | null;
  y_values?: string[] | null;
  /** Gauge ceiling; when absent the renderer derives one from the value. */
  max_value?: number | null;
}

export function isChatChart(value: unknown): value is ChatChart {
  if (!value || typeof value !== "object") return false;
  const chart = value as ChatChart;
  return (
    typeof chart.id === "string" &&
    typeof chart.title === "string" &&
    typeof chart.type === "string" &&
    Array.isArray(chart.series) &&
    Array.isArray(chart.rows)
  );
}

export function chartValue(
  value: number | string | null | undefined,
  format: ChatKpiFormat = "number",
  compact = false,
): string {
  if (value == null || value === "") return "—";
  if (format === "text") return String(value);
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  switch (format) {
    case "currency": {
      const abs = Math.abs(n);
      if (compact && abs >= 1000) {
        return `$${new Intl.NumberFormat("en-US", {
          notation: "compact",
          maximumFractionDigits: 1,
        }).format(n)}`;
      }
      return `$${n.toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    }
    case "percent":
      return `${n.toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
    case "rating":
      return `${n.toFixed(1)}★`;
    case "ratio":
      return `${n.toFixed(2)}×`;
    case "seconds": {
      const total = Math.max(0, Math.round(n));
      if (total < 60) return `${total}s`;
      const minutes = Math.floor(total / 60);
      const seconds = total % 60;
      if (minutes < 60) return `${minutes}m${seconds ? ` ${seconds}s` : ""}`;
      const hours = Math.floor(minutes / 60);
      return `${hours}h ${minutes % 60}m`;
    }
    default:
      if (compact && Math.abs(n) >= 1000) {
        return new Intl.NumberFormat("en-US", {
          notation: "compact",
          maximumFractionDigits: 1,
        }).format(n);
      }
      return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
}

export function chartLabel(label: string): string {
  if (!label) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(label)) {
    const date = new Date(`${label}T00:00:00`);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }
  }
  if (/^\d{4}-\d{2}$/.test(label)) {
    const date = new Date(`${label}-01T00:00:00`);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleDateString(undefined, { month: "short", year: "numeric" });
    }
  }
  return label;
}

export function truncateLabel(label: string, max = 18): string {
  const value = chartLabel(label);
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}
