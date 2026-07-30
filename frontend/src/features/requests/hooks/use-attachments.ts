"use client";

import { useQuery } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { attachmentService } from "@/services/attachment-service";

export function useAttachments(requestId: string) {
  return useQuery({
    queryKey: requestKeys.attachments(requestId),
    queryFn: () => attachmentService.list(requestId),
    staleTime: 10_000,
  });
}
