import type { LucideIcon } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/patterns/error-state";
import { Caption, SectionHeading } from "@/components/patterns/typography";
import { AiBadge } from "@/features/ai/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { AiInsight } from "@/types/ai";

interface AiInsightCardProps {
  title: string;
  icon?: LucideIcon;
  data: AiInsight | undefined;
  isLoading: boolean;
  isError: boolean;
  onRetry?: () => void;
  className?: string;
}

// AI-generated summaries vary widely in length — a long one placed next to
// short ones in the same grid row previously made the row's card heights
// wildly uneven. Past this length, the text is clamped to a fixed number
// of lines with a "Show more"/"Show less" toggle, matching every other
// card's height instead of stretching the whole row to fit the longest one.
const COLLAPSE_THRESHOLD_CHARS = 220;
const COLLAPSED_LINE_CLAMP_CLASSNAME = "line-clamp-6";

/** Generic card for rendering any `AiInsight` — a title, a loading
 * skeleton, an error state with retry, and the content itself. When
 * `data.is_fallback` is true, this card shows a muted "AI unavailable"
 * caption instead of the `AiBadge`, so the UI never presents a computed
 * fallback as if it were genuinely AI-written. */
export function AiInsightCard({
  title,
  icon: Icon,
  data,
  isLoading,
  isError,
  onRetry,
  className,
}: AiInsightCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isCollapsible = (data?.text.length ?? 0) > COLLAPSE_THRESHOLD_CHARS;

  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <SectionHeading className="flex items-center gap-2">
          {Icon && <Icon className="size-4 text-muted-foreground" aria-hidden />}
          {title}
        </SectionHeading>
        {data && !data.is_fallback && <AiBadge />}
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}
        {!isLoading && isError && (
          <ErrorState message="Couldn't generate this insight." onRetry={onRetry} />
        )}
        {!isLoading && !isError && data && (
          <div className="space-y-2">
            <p
              className={cn(
                "text-sm leading-relaxed whitespace-pre-line text-foreground",
                isCollapsible && !isExpanded && COLLAPSED_LINE_CLAMP_CLASSNAME,
              )}
            >
              {data.text}
            </p>
            {isCollapsible && (
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={() => setIsExpanded((prev) => !prev)}
              >
                {isExpanded ? "Show less" : "Show more"}
              </Button>
            )}
            {data.is_fallback && (
              <Caption>AI unavailable right now — showing a computed summary instead.</Caption>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
