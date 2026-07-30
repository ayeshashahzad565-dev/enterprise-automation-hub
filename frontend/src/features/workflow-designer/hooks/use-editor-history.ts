"use client";

import { useCallback, useRef, useState } from "react";

const MAX_HISTORY = 50;

/**
 * Pure client-side undo/redo over the editor's in-memory stage list —
 * nothing here is persisted server-side until Save/Publish, so this is
 * plain in-memory state history (past/future stacks), not a backend
 * capability. Capped at `MAX_HISTORY` snapshots to bound memory.
 */
export function useEditorHistory<T>(initial: T) {
  const [present, setPresent] = useState(initial);
  const past = useRef<T[]>([]);
  const future = useRef<T[]>([]);

  const set = useCallback((next: T) => {
    past.current = [...past.current, present].slice(-MAX_HISTORY);
    future.current = [];
    setPresent(next);
  }, [present]);

  const undo = useCallback(() => {
    if (past.current.length === 0) return;
    const previous = past.current[past.current.length - 1];
    past.current = past.current.slice(0, -1);
    future.current = [present, ...future.current];
    setPresent(previous);
  }, [present]);

  const redo = useCallback(() => {
    if (future.current.length === 0) return;
    const next = future.current[0];
    future.current = future.current.slice(1);
    past.current = [...past.current, present];
    setPresent(next);
  }, [present]);

  const reset = useCallback((value: T) => {
    past.current = [];
    future.current = [];
    setPresent(value);
  }, []);

  return {
    state: present,
    set,
    undo,
    redo,
    reset,
    canUndo: past.current.length > 0,
    canRedo: future.current.length > 0,
  };
}
