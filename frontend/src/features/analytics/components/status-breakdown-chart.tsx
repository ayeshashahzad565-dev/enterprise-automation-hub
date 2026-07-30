"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";

import { ChartSkeleton } from "@/components/patterns/charts/chart-skeleton";
import type { BarChartDatum } from "@/components/patterns/charts/bar-chart";
import type { StatusBreakdown } from "@/types/analytics";
import { ROUTES } from "@/utils/constants";

// See request-trend-panel.tsx — recharts is deferred to its own chunk.
const BarChart = dynamic(
  () => import("@/components/patterns/charts/bar-chart").then((m) => m.BarChart),
  { ssr: false, loading: () => <ChartSkeleton /> },
);

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  in_review: "In review",
  completed: "Completed",
  rejected: "Rejected",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "var(--status-pending-bg)",
  in_review: "var(--status-in-review-bg)",
  completed: "var(--status-completed-bg)",
  rejected: "var(--status-rejected-bg)",
};

/** Clickable status-breakdown bar chart — a click drills down to a pre-filtered Requests list. */
export function StatusBreakdownChart({
  breakdown,
  height,
}: {
  breakdown: StatusBreakdown;
  /** Forwarded to `BarChart`'s `ResponsiveContainer` — pass `"100%"` when
   * the parent is a flex/grid cell whose height is already determined by
   * a taller sibling (e.g. the Dashboard's "Workflow health" card next to
   * "Recent activity"), so the chart fills the card instead of leaving
   * unused space below a fixed-height chart. Omit to keep `BarChart`'s
   * own fixed default, appropriate when nothing else sets the card's
   * height (e.g. the Analytics page's own Status breakdown card). */
  height?: number | `${number}%`;
}) {
  const router = useRouter();
  const data: BarChartDatum[] = Object.entries(breakdown.counts).map(([status, count]) => ({
    key: status,
    label: STATUS_LABELS[status] ?? status,
    value: count as number,
    color: STATUS_COLORS[status],
  }));

  return (
    <BarChart
      data={data}
      height={height}
      onBarClick={(datum) => router.push(`${ROUTES.requests}?status=${datum.key}`)}
    />
  );
}
