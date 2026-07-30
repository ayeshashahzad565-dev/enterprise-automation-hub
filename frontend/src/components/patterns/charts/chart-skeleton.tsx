import { Skeleton } from "@/components/ui/skeleton";

/** Matches a chart's real footprint so data arrival causes zero layout shift. */
export function ChartSkeleton({ height = 260 }: { height?: number }) {
  return <Skeleton className="w-full" style={{ height }} />;
}
