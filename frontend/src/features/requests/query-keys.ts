import type { ListRequestsParams } from "@/services/request-service";

/** Centralized TanStack Query key factory for the Requests feature. */
export const requestKeys = {
  all: ["requests"] as const,
  lists: () => [...requestKeys.all, "list"] as const,
  list: (params: ListRequestsParams) => [...requestKeys.lists(), params] as const,
  details: () => [...requestKeys.all, "detail"] as const,
  detail: (id: string) => [...requestKeys.details(), id] as const,
  workflow: (id: string) => [...requestKeys.detail(id), "workflow"] as const,
  auditTrail: (id: string) => [...requestKeys.detail(id), "audit-log"] as const,
  comments: (id: string) => [...requestKeys.detail(id), "comments"] as const,
  attachments: (id: string) => [...requestKeys.detail(id), "attachments"] as const,
};
