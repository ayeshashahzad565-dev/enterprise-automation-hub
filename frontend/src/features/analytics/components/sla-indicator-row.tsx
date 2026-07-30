import { AlertTriangle, Clock3 } from "lucide-react";

import { KpiRow as KpiRowPattern } from "@/components/patterns/charts/kpi-card";
import type { SLAMetrics } from "@/types/operational-analytics";

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const hours = seconds / 3600;
  if (hours < 1) return `${Math.round(seconds / 60)}m`;
  return `${hours.toFixed(1)}h`;
}

/** SLA follow-up indicators for the Operational Intelligence tab, shown
 * alongside ``ExecutiveKpiRow``. Deliberately excludes SLA compliance,
 * pending approvals, and overdue approvals — ``ExecutiveKpiRow`` already
 * shows each of those (per the backend's own `ExecutiveKPIs.pending_approvals`/
 * `overdue_approvals` docstrings, they're literally the same
 * `SLAMetrics.pending_stage_count`/`overdue_stage_count` figures reused
 * under a different label, not a second, distinct measurement) — this
 * row only adds the two figures `ExecutiveKpiRow` doesn't already cover. */
export function SlaIndicatorRow({ metrics }: { metrics: SLAMetrics }) {
  return (
    <KpiRowPattern
      items={[
        {
          label: "Overdue requests",
          value: String(metrics.overdue_request_count),
          icon: AlertTriangle,
        },
        {
          label: "Avg. pending age",
          value: formatDuration(
            metrics.average_current_stage_age_hours == null
              ? null
              : metrics.average_current_stage_age_hours * 3600,
          ),
          icon: Clock3,
        },
      ]}
    />
  );
}
