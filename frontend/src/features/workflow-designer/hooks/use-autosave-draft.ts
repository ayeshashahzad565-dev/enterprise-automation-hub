"use client";

import { useEffect, useRef } from "react";

import { useUpdateWorkflowDraft } from "@/features/workflow-designer/hooks/use-update-workflow-draft";
import type { StageDefinition, WorkflowDefinition } from "@/types/workflow-definition";

const AUTOSAVE_DEBOUNCE_MS = 2000;

/**
 * Debounced autosave over the same `update_draft` endpoint the manual
 * "Save draft" button calls — no new backend capability, just calling an
 * existing method on a timer. Only active while `enabled` (the caller
 * disables this for an active/archived version, since `update_draft`
 * rejects edits to an already-active definition server-side anyway).
 */
export function useAutosaveDraft({
  enabled,
  definitionId,
  requestType,
  stages,
  onSaved,
}: {
  enabled: boolean;
  definitionId: string;
  requestType: string;
  stages: StageDefinition[];
  onSaved: (updated: WorkflowDefinition) => void;
}) {
  const mutation = useUpdateWorkflowDraft();
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stagesRef = useRef(stages);
  stagesRef.current = stages;

  useEffect(() => {
    if (!enabled) return;
    if (timeoutRef.current) clearTimeout(timeoutRef.current);

    timeoutRef.current = setTimeout(() => {
      mutation.mutate(
        { id: definitionId, requestType, body: { definition: { stages: stagesRef.current } } },
        { onSuccess: onSaved },
      );
    }, AUTOSAVE_DEBOUNCE_MS);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, definitionId, requestType, stages]);

  return { isSaving: mutation.isPending };
}
