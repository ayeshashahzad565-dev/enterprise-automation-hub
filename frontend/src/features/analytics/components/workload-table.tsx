import { Users } from "lucide-react";

import { EmptyState } from "@/components/patterns/empty-state";
import type { UserMetrics } from "@/types/analytics";

export function WorkloadTable({ users }: { users: UserMetrics[] }) {
  if (users.length === 0) {
    return (
      <EmptyState icon={Users} title="No workload data" description="No approvers/admins found in scope." />
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 text-right font-medium">Pending</th>
              <th className="px-3 py-2 text-right font-medium">Approved</th>
              <th className="px-3 py-2 text-right font-medium">Rejected</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.user_id} className="border-t">
                <td className="px-3 py-2 whitespace-nowrap">{user.full_name}</td>
                <td className="px-3 py-2 text-muted-foreground capitalize whitespace-nowrap">
                  {user.role}
                </td>
                <td className="px-3 py-2 text-right">{user.pending_assigned_count}</td>
                <td className="px-3 py-2 text-right">{user.decisions_approved}</td>
                <td className="px-3 py-2 text-right">{user.decisions_rejected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
