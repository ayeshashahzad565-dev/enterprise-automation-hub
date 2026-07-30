import { XCircle } from "lucide-react";

import { EmptyState } from "@/components/patterns/empty-state";
import type { RejectionBucket } from "@/types/operational-analytics";

export function RejectionHotspotsTable({ buckets }: { buckets: RejectionBucket[] }) {
  if (buckets.length === 0) {
    return (
      <EmptyState icon={XCircle} title="No rejections" description="No decided stages to report on." />
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Stage</th>
              <th className="px-3 py-2 text-right font-medium">Rejection rate</th>
              <th className="px-3 py-2 text-right font-medium">Rejected / decided</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.key} className="border-t">
                <td className="px-3 py-2 whitespace-nowrap">{bucket.key}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {bucket.rejection_rate == null
                    ? "—"
                    : `${Math.round(bucket.rejection_rate * 100)}%`}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap text-muted-foreground">
                  {bucket.rejected_count} / {bucket.decided_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
