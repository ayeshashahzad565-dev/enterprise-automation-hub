import { Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/** A small, reusable pill marking content as AI-generated — used wherever
 * an `AiInsight` is rendered, so a viewer can always tell AI-written
 * content apart from the rest of the page at a glance. */
export function AiBadge({ className }: { className?: string }) {
  return (
    <Badge variant="secondary" className={className}>
      <Sparkles data-icon="inline-start" aria-hidden />
      AI
    </Badge>
  );
}
