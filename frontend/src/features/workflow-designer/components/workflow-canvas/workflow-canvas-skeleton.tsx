import { Skeleton } from "@/components/ui/skeleton";

/** Matches the canvas's real footprint to avoid layout shift, same convention as Phase 4's ChartSkeleton. */
export function WorkflowCanvasSkeleton() {
  return (
    <div className="flex h-full w-full items-center gap-6 rounded-lg border border-dashed p-8">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-24 w-48 shrink-0 rounded-lg" />
      ))}
    </div>
  );
}
