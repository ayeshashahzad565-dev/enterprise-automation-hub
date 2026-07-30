"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { approvalKeys } from "@/features/approvals/query-keys";
import { approvalService } from "@/services/approval-service";
import type { ApprovalInboxItem, DecisionInput } from "@/types/approval";

interface RejectInput {
  stageId: string;
  input: DecisionInput;
}

interface InboxListPage {
  data: ApprovalInboxItem[];
  pagination: { page: number; page_size: number; total_records: number; total_pages: number };
}

/**
 * Optimistically removes the decided stage from every cached inbox list.
 * Also backs the "Request changes" UI action — same endpoint, same
 * behavior, just a different button label upstream.
 */
export function useRejectStage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ stageId, input }: RejectInput) => approvalService.reject(stageId, input),
    onMutate: async ({ stageId }) => {
      await queryClient.cancelQueries({ queryKey: approvalKeys.inboxes() });
      const previousLists = queryClient.getQueriesData<InboxListPage>({
        queryKey: approvalKeys.inboxes(),
      });
      queryClient.setQueriesData<InboxListPage | undefined>(
        { queryKey: approvalKeys.inboxes() },
        (old) => (old ? { ...old, data: old.data.filter((item) => item.stage_id !== stageId) } : old),
      );
      return { previousLists };
    },
    onError: (_err, _vars, context) => {
      context?.previousLists?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data);
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: approvalKeys.inboxes() });
    },
  });
}
