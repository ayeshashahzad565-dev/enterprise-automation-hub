"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { ChartSkeleton } from "@/components/patterns/charts/chart-skeleton";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { useOperationalTrends } from "@/features/analytics/hooks/use-operational-trends";
import type { TimeGranularity } from "@/types/analytics";
import type { OperationalAnalyticsFilters, TrendReport } from "@/types/operational-analytics";

// See request-trend-panel.tsx — recharts is deferred to its own chunk.
const TrendChart = dynamic(
  () => import("@/components/patterns/charts/trend-chart").then((m) => m.TrendChart),
  { ssr: false, loading: () => <ChartSkeleton /> },
);

const GRANULARITIES: TimeGranularity[] = ["day", "week", "month"];

const SERIES: { key: keyof TrendReport; label: string }[] = [
  { key: "completion_trend", label: "Completions" },
  { key: "approval_trend", label: "Approvals" },
  { key: "rejection_trend", label: "Rejections" },
  { key: "average_completion_time_trend", label: "Avg. completion time" },
];

/** Operational execution trends (Milestone 12): completion, approval,
 * and rejection volume, plus average completion-time — one selectable
 * series at a time, reusing the exact same ``TrendChart``/granularity-
 * toggle UX ``RequestTrendPanel`` already established. */
export function OperationalTrendPanel({ filters }: { filters: OperationalAnalyticsFilters }) {
  const [granularity, setGranularity] = useState<TimeGranularity>("day");
  const [series, setSeries] = useState<(typeof SERIES)[number]["key"]>("completion_trend");
  const { data, isLoading, isError, refetch } = useOperationalTrends(granularity, filters);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {SERIES.map((option) => (
            <Button
              key={option.key}
              size="sm"
              variant={option.key === series ? "default" : "outline"}
              onClick={() => setSeries(option.key)}
            >
              {option.label}
            </Button>
          ))}
        </div>
        <div className="flex gap-1">
          {GRANULARITIES.map((option) => (
            <Button
              key={option}
              size="sm"
              variant={option === granularity ? "default" : "outline"}
              onClick={() => setGranularity(option)}
            >
              {option[0].toUpperCase() + option.slice(1)}
            </Button>
          ))}
        </div>
      </div>
      {isLoading ? (
        <ChartSkeleton />
      ) : isError || !data ? (
        <ErrorState message="Couldn't load operational trends." onRetry={() => refetch()} />
      ) : (
        <TrendChart points={data[series].points} />
      )}
    </div>
  );
}
