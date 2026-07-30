"use client";

import { Building2, X } from "lucide-react";
import { useState } from "react";

import { ChartSkeleton } from "@/components/patterns/charts/chart-skeleton";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDepartmentOperationalComparison } from "@/features/analytics/hooks/use-department-operational-comparison";
import type { OperationalAnalyticsFilters } from "@/types/operational-analytics";

function formatPercent(value: number | null): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

/**
 * Department comparison for operational figures (SLA compliance,
 * throughput, backlog) — the same free-text "add a department" UX as
 * ``DepartmentComparePanel``, since no department-enumeration endpoint
 * exists anywhere in the backend (that panel's own documented
 * constraint), rendered as a table rather than a bar chart because
 * these are several heterogeneous metrics per department, not one
 * comparable value.
 */
export function DepartmentOperationalPanel({
  filters,
}: {
  filters: Pick<OperationalAnalyticsFilters, "created_after" | "created_before">;
}) {
  const [departments, setDepartments] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const results = useDepartmentOperationalComparison(departments, filters);

  function addDepartment() {
    const trimmed = input.trim();
    if (trimmed && !departments.includes(trimmed)) {
      setDepartments((previous) => [...previous, trimmed]);
    }
    setInput("");
  }

  // isLoading/isError are checked *before* building `rows` below — a
  // failed or still-in-flight query must never be silently dropped from
  // the comparison as if it were simply not added (see
  // UserMetricsLookupPanel's identical isLoading/isError/content
  // ordering, this panel's reference pattern for a query-driven UI).
  const isLoading = results.some((result) => result.isLoading);
  const hasError = results.some((result) => result.isError || (!result.isLoading && !result.data));

  const rows = results
    .map((result, index) => ({ department: departments[index], data: result.data }))
    .filter((row): row is { department: string; data: NonNullable<typeof row.data> } => !!row.data);

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
        <EmptyState
          icon={Building2}
          title="No departments added"
          description="Add a department to compare its SLA compliance, throughput, and backlog."
        />
      ) : isLoading ? (
        <ChartSkeleton />
      ) : hasError ? (
        <ErrorState
          message="Couldn't load one or more departments."
          onRetry={() => results.forEach((result) => result.refetch())}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Department</th>
                  <th className="px-3 py-2 text-right font-medium">SLA compliance</th>
                  <th className="px-3 py-2 text-right font-medium">Throughput/day</th>
                  <th className="px-3 py-2 text-right font-medium">Active</th>
                  <th className="px-3 py-2 text-right font-medium">Backlog</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ department, data }) => (
                  <tr key={department} className="border-t">
                    <td className="px-3 py-2 font-medium whitespace-nowrap">{department}</td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {formatPercent(data.sla_compliance_percentage)}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {data.throughput_per_day == null ? "—" : data.throughput_per_day.toFixed(1)}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {data.active_workload}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {data.backlog_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
