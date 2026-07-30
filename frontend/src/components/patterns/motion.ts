/**
 * Motion guidelines for this design system — named constants, not a
 * runtime animation library. Every custom transition in this codebase
 * (most are already handled by each shadcn/base-ui primitive's own
 * built-in `data-[state=open|closed]` transitions) should use these
 * durations/easings rather than picking new ones ad hoc, and must respect
 * `prefers-reduced-motion` via Tailwind's `motion-reduce:` variant.
 *
 * Rules:
 * - Durations: 120–200ms. Nothing in this app animates slower than that.
 * - Easing: ease-out on enter, ease-in on exit. No spring/bounce effects.
 * - Every custom (non-primitive) transition must be paired with a
 *   `motion-reduce:transition-none` (or equivalent) so it's fully
 *   disabled for users who've requested reduced motion.
 */

export const MOTION_DURATION = {
  fast: "duration-120",
  base: "duration-150",
  slow: "duration-200",
} as const;

export const MOTION_EASE = {
  enter: "ease-out",
  exit: "ease-in",
} as const;

/** A ready-to-spread className fragment for a simple fade/slide entrance. */
export const FADE_IN_CLASSNAME =
  "animate-in fade-in slide-in-from-bottom-1 duration-150 ease-out motion-reduce:animate-none";
