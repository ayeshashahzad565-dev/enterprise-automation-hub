"use client";

import { useQuery } from "@tanstack/react-query";

import { approvalKeys } from "@/features/approvals/query-keys";
import { approvalService, type ListInboxParams } from "@/services/approval-service";

export function useApprovalInbox(params: ListInboxParams) {
  return useQuery({
    queryKey: approvalKeys.inbox(params),
    queryFn: () => approvalService.listInbox(params),
    staleTime: 15_000,
    placeholderData: (previousData) => previousData,
  });
}
