import { Building2, CheckSquare, GitBranch, Users } from "lucide-react";

import { KpiRow } from "@/components/patterns/charts/kpi-card";
import { Caption, SectionHeading } from "@/components/patterns/typography";
import { ActivityItem } from "@/features/activity/components/activity-item";
import type { AdminDashboard } from "@/types/admin";

/** Reuses Analytics' `KpiRow`/`KpiCard` and Phase 5's `ActivityItem` —
 * per the spec's "reuse Analytics components wherever possible"
 * instruction — rather than building new metric-card primitives. */
export function AdminDashboardMetrics({ dashboard }: { dashboard: AdminDashboard }) {
  const definitionCount = Object.values(dashboard.workflow_definition_counts).reduce(
    (sum, count) => sum + count,
    0,
  );

  return (
    <div className="space-y-6">
      <KpiRow
        items={[
          { label: "Total users", value: String(dashboard.total_users), icon: Users },
          { label: "Departments", value: String(dashboard.department_count), icon: Building2 },
          {
            label: "Pending approvals",
            value: String(dashboard.pending_approvals_count),
            icon: CheckSquare,
          },
          { label: "Workflow definitions", value: String(definitionCount), icon: GitBranch },
        ]}
      />
      <Caption>
        Workflow definitions counted only for known request types — no cross-type &ldquo;list every
        definition&rdquo; backend method exists.
      </Caption>

      <div className="space-y-2">
        <SectionHeading>Recent administrative actions</SectionHeading>
        <div className="space-y-1">
          {dashboard.recent_activity.length > 0 ? (
            dashboard.recent_activity.map((entry) => <ActivityItem key={entry.id} entry={entry} />)
          ) : (
            <p className="text-sm text-muted-foreground">No recent activity.</p>
          )}
        </div>
      </div>
    </div>
  );
}
