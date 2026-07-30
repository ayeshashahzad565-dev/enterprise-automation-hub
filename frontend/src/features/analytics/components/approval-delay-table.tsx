import { Clock } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/patterns/empty-state";
import type { PendingApprovalAge } from "@/types/operational-analytics";
import { ROUTES } from "@/utils/constants";

/** Longest-pending / top-delayed-requests table — the Operational
 * Intelligence tab's approval-delay dataset, reusing the same plain
 * ``<table>`` pattern ``WorkloadTable`` already established for
 * lightweight, read-only analytics tables. */
export function ApprovalDelayTable({ items }: { items: PendingApprovalAge[] }) {
  if (items.length === 0) {
    return (
      <EmptyState icon={Clock} title="No pending approvals" description="Nothing is currently waiting." />
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Request</th>
              <th className="px-3 py-2 font-medium">Stage</th>
              <th className="px-3 py-2 font-medium">Department</th>
              <th className="px-3 py-2 text-right font-medium">Age</th>
              <th className="px-3 py-2 text-right font-medium">SLA</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.stage_id} className="border-t">
                <td className="px-3 py-2 whitespace-nowrap">
                  <Link
                    href={ROUTES.request(item.request_id)}
                    className="font-medium hover:underline"
                  >
                    {item.request_title}
                  </Link>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">
                  {item.stage_name}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">
                  {item.department ?? "—"}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {item.age_hours.toFixed(1)}h
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {item.is_overdue ? (
                    <span className="inline-flex items-center rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
                      Overdue
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      {item.sla_hours == null ? "—" : `${item.sla_hours}h`}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
