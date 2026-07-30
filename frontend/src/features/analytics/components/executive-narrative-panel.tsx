import { ErrorState } from "@/components/patterns/error-state";
import { SectionHeading } from "@/components/patterns/typography";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/** Owns its own loading/error states, mirroring `AiInsightCard` (an
 * analogous "one card, one piece of generated text" shape) — previously
 * this panel was only ever rendered conditionally on `summaryQuery.data`,
 * which meant a failed or in-flight query made the whole card silently
 * disappear instead of showing a skeleton or a retryable error. */
export function ExecutiveNarrativePanel({
  narrative,
  isLoading,
  isError,
  onRetry,
  className,
}: {
  narrative: string | undefined;
  isLoading: boolean;
  isError: boolean;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <SectionHeading>Executive summary</SectionHeading>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : isError || !narrative ? (
          <ErrorState message="Couldn't load the executive summary." onRetry={onRetry} />
        ) : (
          <p className="text-sm leading-relaxed text-muted-foreground">{narrative}</p>
        )}
      </CardContent>
    </Card>
  );
}
