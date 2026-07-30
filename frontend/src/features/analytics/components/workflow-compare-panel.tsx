"use client";

import { X } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { ChartSkeleton } from "@/components/patterns/charts/chart-skeleton";
import type { BarChartDatum } from "@/components/patterns/charts/bar-chart";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useWorkflowComparison } from "@/features/analytics/hooks/use-workflow-comparison";
import type { AnalyticsFilters } from "@/types/analytics";

// See request-trend-panel.tsx — recharts is deferred to its own chunk.
const BarChart = dynamic(
  () => import("@/components/patterns/charts/bar-chart").then((m) => m.BarChart),
  { ssr: false, loading: () => <ChartSkeleton /> },
);

/**
 * No request-type-enumeration endpoint exists anywhere in the backend —
 * the same honest constraint `DepartmentComparePanel` documents for
 * departments — so workflow (request) types to compare are added by
 * free text, one `get_workflow_metrics` call per chip via
 * `useWorkflowComparison`.
 */
export function WorkflowComparePanel({
  filters,
}: {
  filters: Omit<AnalyticsFilters, "request_type">;
}) {
  const [requestTypes, setRequestTypes] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const results = useWorkflowComparison(requestTypes, filters);

  function addRequestType() {
    const trimmed = input.trim();
    if (trimmed && !requestTypes.includes(trimmed)) {
      setRequestTypes((previous) => [...previous, trimmed]);
    }
    setInput("");
  }

  // isLoading/isError are checked *before* building `data` below — a
  // failed or still-in-flight query must never be silently dropped from
  // the comparison as if it were simply not added (see
  // UserMetricsLookupPanel's identical isLoading/isError/content
  // ordering, this panel's reference pattern for a query-driven UI).
  const isLoading = results.some((result) => result.isLoading);
  const hasError = results.some((result) => result.isError || (!result.isLoading && !result.data));

  const data: BarChartDatum[] = results
    .map((result, index) => {
      const requestType = requestTypes[index];
      if (!result.data) return null;
      return { key: requestType, label: requestType, value: result.data.status_breakdown.total };
    })
    .filter((datum): datum is BarChartDatum => datum !== null);

  return (
    <div className="space-y-3">
      {requestTypes.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {requestTypes.map((requestType) => (
            <span
              key={requestType}
              className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
            >
              {requestType}
              <button
                type="button"
                aria-label={`Remove ${requestType}`}
                onClick={() =>
                  setRequestTypes((previous) => previous.filter((r) => r !== requestType))
                }
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addRequestType();
            }
          }}
          placeholder="Add a workflow type..."
          className="h-8 max-w-48"
        />
        <Button size="sm" variant="outline" onClick={addRequestType}>
          Add
        </Button>
      </div>
      {requestTypes.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Add a workflow type (e.g. expense_reimbursement) to compare its request volume.
        </p>
      ) : isLoading ? (
        <ChartSkeleton />
      ) : hasError ? (
        <ErrorState
          message="Couldn't load one or more workflow types."
          onRetry={() => results.forEach((result) => result.refetch())}
        />
      ) : (
        <BarChart data={data} height={Math.max(120, data.length * 44)} />
      )}
    </div>
  );
}
