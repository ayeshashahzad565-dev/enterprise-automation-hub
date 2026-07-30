"use client";

import { useEffect, useRef, useState } from "react";

const DRAFT_STORAGE_KEY = "eah:create-request-draft";
const AUTOSAVE_DEBOUNCE_MS = 500;

export interface RequestDraft {
  request_type?: string;
  title?: string;
  description?: string;
  department?: string;
}

function isNonEmptyDraft(draft: RequestDraft): boolean {
  return Object.values(draft).some((value) => value && value.trim().length > 0);
}

/** Frontend-only autosave for the Create Request form — never sent to the backend. */
export function useRequestDraft() {
  const [draft, setDraft] = useState<RequestDraft | null>(null);
  const [dismissed, setDismissed] = useState(false);
  // `RequestForm`'s useForm() only reads `defaultValues` once, at mount —
  // since reading localStorage happens in an effect (after that first
  // render), consumers must wait for `isReady` before mounting the form,
  // or the recovered draft would silently fail to populate its fields.
  const [isReady, setIsReady] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as RequestDraft;
        if (isNonEmptyDraft(parsed)) {
          setDraft(parsed);
        }
      }
    } catch {
      // Corrupted or inaccessible storage — autosave recovery silently skipped.
    } finally {
      setIsReady(true);
    }
  }, []);

  function save(values: RequestDraft): void {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      try {
        if (isNonEmptyDraft(values)) {
          window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(values));
        }
      } catch {
        // Storage unavailable (e.g. private browsing) — autosave silently disabled.
      }
    }, AUTOSAVE_DEBOUNCE_MS);
  }

  function clear(): void {
    try {
      window.localStorage.removeItem(DRAFT_STORAGE_KEY);
    } catch {
      // ignore
    }
    setDraft(null);
  }

  function dismiss(): void {
    setDismissed(true);
  }

  return { draft: dismissed ? null : draft, isReady, save, clear, dismiss };
}
