import { Activity, AlertTriangle, CheckCircle2, Clock, ListChecks, TrendingUp, XCircle } from "lucide-react";

import { KpiRow as KpiRowPattern } from "@/components/patterns/charts/kpi-card";
import type { DashboardMetrics } from "@/types/analytics";

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const hours = seconds / 3600;
  if (hours < 1) return `${Math.round(seconds / 60)}m`;
  return `${hours.toFixed(1)}h`;
}

function formatPercent(value: number | null): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Renders a DashboardMetrics slice as the KPI row every dashboard tab shares. */
export function DashboardKpiRow({ metrics }: { metrics: DashboardMetrics }) {
  return (
    <KpiRowPattern
      items={[
        { label: "Total requests", value: String(metrics.total_requests), icon: ListChecks },
        { label: "Active", value: String(metrics.active_requests), icon: Activity },
        { label: "Completed", value: String(metrics.completed_requests), icon: CheckCircle2 },
        { label: "Rejected", value: String(metrics.rejected_requests), icon: XCircle },
        {
          label: "Completion rate",
          value: formatPercent(metrics.approval_metrics.throughput.completion_rate),
          icon: TrendingUp,
        },
        {
          label: "Avg. decision time",
          value: formatDuration(metrics.approval_metrics.approval_latency_seconds),
          icon: Clock,
        },
        {
          label: "Escalations",
          value:
            metrics.approval_metrics.escalation_count == null
              ? "—"
              : String(metrics.approval_metrics.escalation_count),
          icon: AlertTriangle,
        },
      ]}
    />
  );
}
