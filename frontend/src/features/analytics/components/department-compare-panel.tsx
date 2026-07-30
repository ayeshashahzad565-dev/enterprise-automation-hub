"use client";

import { X } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { ChartSkeleton } from "@/components/patterns/charts/chart-skeleton";
import type { BarChartDatum } from "@/components/patterns/charts/bar-chart";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDepartmentComparison } from "@/features/analytics/hooks/use-department-comparison";
import type { AnalyticsFilters } from "@/types/analytics";

// See request-trend-panel.tsx — recharts is deferred to its own chunk.
const BarChart = dynamic(
  () => import("@/components/patterns/charts/bar-chart").then((m) => m.BarChart),
  { ssr: false, loading: () => <ChartSkeleton /> },
);

/**
 * No department-enumeration endpoint exists anywhere in the backend (the
 * same honest constraint Phase 2 hit for request types) — departments to
 * compare are added by free text, one `get_department_metrics` call per
 * chip via `useDepartmentComparison`.
 */
export function DepartmentComparePanel({
  filters,
}: {
  filters: Pick<AnalyticsFilters, "created_after" | "created_before">;
}) {
  const [departments, setDepartments] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const results = useDepartmentComparison(departments, filters);

  function addDepartment() {
    const trimmed = input.trim();
    if (trimmed && !departments.includes(trimmed)) {
      setDepartments((previous) => [...previous, trimmed]);
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
      const department = departments[index];
      if (!result.data) return null;
      return { key: department, label: department, value: result.data.status_breakdown.total };
    })
    .filter((datum): datum is BarChartDatum => datum !== null);

  return (
    <div className="space-y-3">
      {departments.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {departments.map((department) => (
            <span
              key={department}
              className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
            >
              {department}
              <button
                type="button"
                aria-label={`Remove ${department}`}
                onClick={() => setDepartments((previous) => previous.filter((d) => d !== department))}
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
              addDepartment();
            }
          }}
          placeholder="Add a department..."
          className="h-8 max-w-48"
        />
        <Button size="sm" variant="outline" onClick={addDepartment}>
          Add
        </Button>
      </div>
      {departments.length === 0 ? (
        <p className="text-sm text-muted-foreground">Add a department to compare its request volume.</p>
      ) : isLoading ? (
        <ChartSkeleton />
      ) : hasError ? (
        <ErrorState
          message="Couldn't load one or more departments."
          onRetry={() => results.forEach((result) => result.refetch())}
        />
      ) : (
        <BarChart data={data} height={Math.max(120, data.length * 44)} />
      )}
    </div>
  );
}
