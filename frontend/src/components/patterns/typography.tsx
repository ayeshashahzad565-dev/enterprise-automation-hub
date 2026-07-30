import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/** Page-level heading — one per page, at the top of a PageHeader. */
export function PageTitle({ className, ...props }: ComponentProps<"h1">) {
  return <h1 className={cn("text-display font-bold", className)} {...props} />;
}

/** A section/card heading (e.g. a Card's own title row). */
export function SectionHeading({ className, ...props }: ComponentProps<"h2">) {
  return <h2 className={cn("text-heading font-semibold", className)} {...props} />;
}

/** A tertiary heading nested under a SectionHeading (e.g. a card's own
 * label row) — the tier the codebase was previously missing, forcing
 * one-off className combos wherever a heading smaller than SectionHeading
 * but heavier than body text was needed. */
export function SubHeading({ className, ...props }: ComponentProps<"h3">) {
  return <h3 className={cn("text-body font-semibold", className)} {...props} />;
}

/** Secondary, de-emphasized text — timestamps, helper copy, field hints. */
export function Caption({ className, ...props }: ComponentProps<"p">) {
  return <p className={cn("text-caption text-muted-foreground", className)} {...props} />;
}

/** Monospaced text for ids, checksums, and other literal values. */
export function Mono({ className, ...props }: ComponentProps<"span">) {
  return <span className={cn("font-mono text-caption", className)} {...props} />;
}

/** A single numeric statistic (KPI value, metric card figure) — visually
 * matches PageTitle's size/weight but is a distinct component since a
 * metric is data, not a heading; previously this exact class combination
 * was copy-pasted independently in kpi-card.tsx, the analytics page, and
 * the admin department panel. */
export function Metric({ className, ...props }: ComponentProps<"p">) {
  return <p className={cn("text-title font-semibold tabular-nums", className)} {...props} />;
}
