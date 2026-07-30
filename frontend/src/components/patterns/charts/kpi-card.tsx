import type { LucideIcon } from "lucide-react";

import { Caption, Metric } from "@/components/patterns/typography";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface KpiItem {
  label: string;
  value: string;
  icon?: LucideIcon;
}

export function KpiCard({ label, value, icon: Icon, className }: KpiItem & { className?: string }) {
  return (
    // [--card-spacing] pins internal padding at 20px on every side — this
    // component's own density target, distinct from the shared Card
    // primitive's "sm"=16px/"default"=24px tiers.
    <Card size="sm" className={cn("[--card-spacing:1.25rem]", className)}>
      {/* Icon, label, and value are stacked in one centered column rather
       * than icon-beside-label: a single unbreakable word (e.g.
       * "Completed", "Departments") can overflow past its own box's
       * padding/reserved space when there's nothing forcing it to wrap,
       * which made an icon positioned beside or over that text collide
       * with it. Stacking removes any shared horizontal space between
       * icon and text, so overlap isn't possible regardless of label or
       * card width. */}
      <CardContent className="flex flex-col items-center gap-1 text-center">
        {Icon && <Icon className="size-5 text-muted-foreground" aria-hidden />}
        {/* min-h-10 reserves space for a label up to 3 lines at this
         * tighter 1.15 line-height (labels here range from "Completed", 1
         * line, to "Org. completion rate", up to 3 lines depending on card
         * width) — so the Metric value below always starts at the same y
         * regardless of actual label line count. */}
        <Caption className="min-h-10 font-medium" style={{ lineHeight: 1.15 }}>
          {label}
        </Caption>
        <Metric>{value}</Metric>
      </CardContent>
    </Card>
  );
}

// auto-fit (not auto-fill) so a partial last row's cards stretch to fill
// the full row width instead of leaving unused trailing space — a fixed
// per-breakpoint column count (e.g. 7 at xl) left a visible gap whenever
// the item count didn't divide evenly (10 items at xl wrapped 7+3, the
// 3 stranded on their own row at card width instead of filling it).
const KPI_ROW_GRID_CLASSNAME = "grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-3";

/** A responsive row of KPI cards — the one place a metric row is laid out, reused by every dashboard tab. */
export function KpiRow({ items }: { items: KpiItem[] }) {
  return (
    <div className={KPI_ROW_GRID_CLASSNAME}>
      {items.map((item) => (
        <KpiCard key={item.label} {...item} />
      ))}
    </div>
  );
}

export function KpiRowSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className={KPI_ROW_GRID_CLASSNAME}>
      {Array.from({ length: count }).map((_, index) => (
        <Card key={index} size="sm" className="[--card-spacing:1.25rem]">
          <CardContent className="flex flex-col gap-1">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-6 w-12" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
