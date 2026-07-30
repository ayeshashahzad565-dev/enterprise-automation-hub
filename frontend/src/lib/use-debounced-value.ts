"use client";

import { useEffect, useState } from "react";

/**
 * Returns `value`, updated only after `delayMs` has passed without a
 * further change. Extracted once search needed it in three places
 * (command palette, the dedicated search page, advanced-filter free
 * text) — every debounce in this app before now was a one-off, hand-
 * rolled `setTimeout`/`clearTimeout` local to its single call site.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timeout = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timeout);
  }, [value, delayMs]);

  return debounced;
}
