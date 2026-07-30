"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { ChartSkeleton } from "@/components/patterns/charts/chart-skeleton";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { useTrend } from "@/features/analytics/hooks/use-trend";
import type { AnalyticsFilters, TimeGranularity } from "@/types/analytics";

// recharts (~+100kB) is only needed once a request actually resolves with
// points to draw — deferred to its own chunk instead of the route's initial
// JS so pages that render this panel parse/hydrate faster.
const TrendChart = dynamic(
  () => import("@/components/patterns/charts/trend-chart").then((m) => m.TrendChart),
  { ssr: false, loading: () => <ChartSkeleton /> },
);

const GRANULARITIES: TimeGranularity[] = ["day", "week", "month"];

export function RequestTrendPanel({
  filters,
}: {
  filters: Omit<AnalyticsFilters, "request_type"> & { request_type?: string };
}) {
  const [granularity, setGranularity] = useState<TimeGranularity>("day");
  const { data, isLoading, isError, refetch } = useTrend(granularity, filters);

  return (
    <div className="space-y-2">
      <div className="flex justify-end gap-1">
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
      {isLoading ? (
        <ChartSkeleton />
      ) : isError || !data ? (
        <ErrorState message="Couldn't load the request trend." onRetry={() => refetch()} />
      ) : (
        <TrendChart points={data.points} />
      )}
    </div>
  );
}
