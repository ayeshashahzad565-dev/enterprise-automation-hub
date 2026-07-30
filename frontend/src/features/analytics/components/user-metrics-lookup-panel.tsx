"use client";

import { CheckCircle2, Clock, ListChecks, XCircle } from "lucide-react";
import { useState } from "react";

import { KpiRow, KpiRowSkeleton } from "@/components/patterns/charts/kpi-card";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useUserMetrics } from "@/features/analytics/hooks/use-user-metrics";

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const hours = seconds / 3600;
  if (hours < 1) return `${Math.round(seconds / 60)}m`;
  return `${hours.toFixed(1)}h`;
}

/**
 * No user-directory search endpoint is exposed to this page (only
 * `admin/users` is, gated to admins) — a user id is looked up by free
 * text, the same honest "no enumeration endpoint" constraint
 * `DepartmentComparePanel`/`WorkflowComparePanel` document, via
 * `GET /analytics/users/{userId}`.
 */
export function UserMetricsLookupPanel() {
  const [input, setInput] = useState("");
  const [userId, setUserId] = useState<string | undefined>(undefined);
  const query = useUserMetrics(userId);

  function lookup() {
    setUserId(input.trim() || undefined);
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              lookup();
            }
          }}
          placeholder="Paste a user id..."
          className="h-8 max-w-72"
        />
        <Button size="sm" variant="outline" onClick={lookup}>
          Look up
        </Button>
      </div>
      {!userId ? (
        <p className="text-sm text-muted-foreground">
          Paste a user&apos;s id to see their approval activity.
        </p>
      ) : query.isLoading ? (
        <KpiRowSkeleton count={4} />
      ) : query.isError || !query.data ? (
        <ErrorState message="Couldn't find a user with that id." onRetry={() => query.refetch()} />
      ) : (
        <KpiRow
          items={[
            { label: "Name", value: query.data.full_name, icon: ListChecks },
            {
              label: "Approved",
              value: String(query.data.decisions_approved),
              icon: CheckCircle2,
            },
            { label: "Rejected", value: String(query.data.decisions_rejected), icon: XCircle },
            {
              label: "Pending assigned",
              value: String(query.data.pending_assigned_count),
              icon: Clock,
            },
            {
              label: "Avg. decision time",
              value: formatDuration(query.data.average_decision_seconds),
              icon: Clock,
            },
          ]}
        />
      )}
    </div>
  );
}
