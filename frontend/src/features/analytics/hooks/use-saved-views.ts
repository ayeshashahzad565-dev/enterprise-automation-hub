"use client";

import { useEffect, useState } from "react";

/**
 * Named, localStorage-persisted filter presets for the Analytics Explorer
 * — frontend-only, no backend concept of a "saved view" exists. Mirrors
 * the shape Phase 3 introduced for the Approvals inbox; feature-scoped
 * again rather than promoted to `components/patterns/`, since only this
 * module needs it so far.
 */
export interface AnalyticsSavedView {
  name: string;
  department?: string;
  requestType?: string;
  createdAfter?: string;
  createdBefore?: string;
}

const STORAGE_KEY = "eah:analytics-saved-views";

export function useSavedViews() {
  const [views, setViews] = useState<AnalyticsSavedView[]>([]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setViews(JSON.parse(raw) as AnalyticsSavedView[]);
    } catch {
      // ignore corrupted preference
    }
  }, []);

  function persist(next: AnalyticsSavedView[]) {
    setViews(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // storage unavailable — preference simply won't persist
    }
  }

  function saveView(view: AnalyticsSavedView) {
    persist([...views.filter((existing) => existing.name !== view.name), view]);
  }

  function removeView(name: string) {
    persist(views.filter((existing) => existing.name !== name));
  }

  return { views, saveView, removeView };
}
