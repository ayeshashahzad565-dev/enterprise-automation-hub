"use client";

import { useQuery } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { commentService } from "@/services/comment-service";

export function useComments(requestId: string) {
  return useQuery({
    queryKey: requestKeys.comments(requestId),
    queryFn: () => commentService.list(requestId),
    staleTime: 10_000,
  });
}
