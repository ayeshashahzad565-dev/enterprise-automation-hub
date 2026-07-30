"use client";

import { useEffect, useState } from "react";

/**
 * Named, localStorage-persisted filter/column-visibility presets for the
 * Approval Inbox — frontend-only, since no backend concept of a "saved
 * view" exists (see the Phase 3 migration plan's scoping notes).
 * Feature-scoped for now rather than promoted to `components/patterns/`,
 * since no other module needs it yet.
 */
export interface SavedView {
  name: string;
  requestType?: string;
  department?: string;
  columnVisibility: Record<string, boolean>;
}

const STORAGE_KEY = "eah:approvals-saved-views";

export function useSavedViews() {
  const [views, setViews] = useState<SavedView[]>([]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setViews(JSON.parse(raw) as SavedView[]);
    } catch {
      // ignore corrupted preference
    }
  }, []);

  function persist(next: SavedView[]) {
    setViews(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // storage unavailable — preference simply won't persist
    }
  }

  function saveView(view: SavedView) {
    persist([...views.filter((existing) => existing.name !== view.name), view]);
  }

  function removeView(name: string) {
    persist(views.filter((existing) => existing.name !== name));
  }

  return { views, saveView, removeView };
}
