import {
  Activity,
  AlertOctagon,
  CheckCircle2,
  Clock,
  Gauge,
  ListChecks,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { KpiRow as KpiRowPattern } from "@/components/patterns/charts/kpi-card";
import type { ExecutiveKPIs } from "@/types/operational-analytics";

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

/** Renders ``ExecutiveKPIs`` (Milestone 12) as a KPI card row — the
 * single-screen composite an executive dashboard needs, reusing the same
 * ``KpiRow`` pattern component ``DashboardKpiRow`` already established. */
export function ExecutiveKpiRow({ kpis }: { kpis: ExecutiveKPIs }) {
  return (
    <KpiRowPattern
      items={[
        {
          label: "Avg. approval time",
          value: formatDuration(kpis.average_approval_seconds),
          icon: Clock,
        },
        {
          label: "Avg. completion time",
          value: formatDuration(kpis.average_workflow_completion_seconds),
          icon: ListChecks,
        },
        {
          label: "SLA compliance",
          value: formatPercent(kpis.sla_compliance_percentage),
          icon: ShieldCheck,
        },
        { label: "Active requests", value: String(kpis.active_requests), icon: Activity },
        { label: "Completed", value: String(kpis.completed_requests), icon: CheckCircle2 },
        { label: "Pending approvals", value: String(kpis.pending_approvals), icon: TrendingUp },
        {
          label: "Overdue approvals",
          value: String(kpis.overdue_approvals),
          icon: AlertOctagon,
        },
        { label: "Rejection rate", value: formatPercent(kpis.rejection_rate), icon: TrendingDown },
        {
          label: "Throughput/day",
          value: kpis.throughput_per_day == null ? "—" : kpis.throughput_per_day.toFixed(1),
          icon: TrendingUp,
        },
        {
          label: "Efficiency score",
          value: formatPercent(kpis.workflow_efficiency_score),
          icon: Gauge,
        },
      ]}
    />
  );
}
