"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { approvalKeys } from "@/features/approvals/query-keys";
import { approvalService } from "@/services/approval-service";
import type { BulkDecisionItem } from "@/types/approval";

/** Not optimistic — see `useBulkApprove`'s docstring for why. */
export function useBulkReject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (items: BulkDecisionItem[]) => approvalService.bulkReject(items),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: approvalKeys.inboxes() });
    },
  });
}
