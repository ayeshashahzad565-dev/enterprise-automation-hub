"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { approvalKeys } from "@/features/approvals/query-keys";
import { approvalService } from "@/services/approval-service";
import type { BulkDecisionItem } from "@/types/approval";

/**
 * Not optimistic: a bulk call's per-item outcome isn't known until the
 * response arrives (partial failure is expected), so the caller reads
 * `data.results` to report success/failure per item, then this refetches
 * the inbox rather than guessing which rows to remove ahead of time.
 */
export function useBulkApprove() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (items: BulkDecisionItem[]) => approvalService.bulkApprove(items),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: approvalKeys.inboxes() });
    },
  });
}
