import type { ListInboxParams } from "@/services/approval-service";

/** Centralized TanStack Query key factory for the Approvals feature. */
export const approvalKeys = {
  all: ["approvals"] as const,
  inboxes: () => [...approvalKeys.all, "inbox"] as const,
  inbox: (params: ListInboxParams) => [...approvalKeys.inboxes(), params] as const,
  eligibility: (requestId: string) => [...approvalKeys.all, "eligibility", requestId] as const,
};
