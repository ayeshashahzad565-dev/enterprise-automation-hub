"use client";

import { useEffect, useState } from "react";

/** True at Tailwind's `lg` breakpoint (1024px) and above. Used only to pick the Designer's resizable-panel-group orientation (horizontal on desktop, stacked/vertical on narrow viewports) — a single mount, no duplicated canvas instance. */
export function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(true);

  useEffect(() => {
    const query = window.matchMedia("(min-width: 1024px)");
    setIsDesktop(query.matches);
    const handler = (event: MediaQueryListEvent) => setIsDesktop(event.matches);
    query.addEventListener("change", handler);
    return () => query.removeEventListener("change", handler);
  }, []);

  return isDesktop;
}
