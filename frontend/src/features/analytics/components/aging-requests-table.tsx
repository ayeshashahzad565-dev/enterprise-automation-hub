import { CheckCircle2 } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/patterns/empty-state";
import type { AgingRequestItem } from "@/types/analytics";
import { ROUTES } from "@/utils/constants";

export function AgingRequestsTable({ items }: { items: AgingRequestItem[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="No aging requests"
        description="Nothing has been pending unusually long."
      />
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {items.map((item) => (
        <li key={item.stage_id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
          <div className="min-w-0">
            <Link href={ROUTES.request(item.request_id)} className="font-medium hover:underline">
              {item.request_title}
            </Link>
            <p className="text-xs text-muted-foreground">
              {item.stage_name} · {item.department ?? "—"}
            </p>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground">{item.age_hours.toFixed(1)}h waiting</span>
        </li>
      ))}
    </ul>
  );
}
