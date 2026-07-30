import { Gauge } from "lucide-react";

import { EmptyState } from "@/components/patterns/empty-state";
import type { DurationBucket } from "@/types/operational-analytics";

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const hours = seconds / 3600;
  if (hours < 1) return `${Math.round(seconds / 60)}m`;
  return `${hours.toFixed(1)}h`;
}

/** A ranked "key -> average decision duration" table — the shared
 * component behind every bottleneck breakdown (slowest stages, slowest
 * workflows, departments causing delay), since ``DurationBucket`` is
 * the same shape for all three (mirrors the backend's own
 * ``app.analytics.operational_dto.DurationBucket`` reuse). */
export function DurationBucketTable({
  buckets,
  keyLabel,
  emptyMessage,
}: {
  buckets: DurationBucket[];
  keyLabel: string;
  emptyMessage: string;
}) {
  if (buckets.length === 0) {
    return <EmptyState icon={Gauge} title="No data" description={emptyMessage} />;
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">{keyLabel}</th>
              <th className="px-3 py-2 text-right font-medium">Avg. duration</th>
              <th className="px-3 py-2 text-right font-medium">Decisions</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.key} className="border-t">
                <td className="px-3 py-2 whitespace-nowrap">{bucket.key}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {formatDuration(bucket.average_seconds)}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap text-muted-foreground">
                  {bucket.count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
