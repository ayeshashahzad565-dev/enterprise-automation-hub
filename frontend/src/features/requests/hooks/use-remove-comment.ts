"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { commentService } from "@/services/comment-service";

export function useRemoveComment(requestId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (commentId: string) => commentService.remove(commentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requestKeys.comments(requestId) });
    },
  });
}
