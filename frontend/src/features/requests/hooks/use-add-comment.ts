"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { useAuth } from "@/providers/auth-provider";
import { commentService } from "@/services/comment-service";
import type { Comment, CommentCreateInput } from "@/types/comment";

interface CommentListPage {
  data: Comment[];
  pagination: { page: number; page_size: number; total_records: number; total_pages: number };
}

/** Optimistically appends the new comment to the thread immediately. */
export function useAddComment(requestId: string) {
  const queryClient = useQueryClient();
  const { user } = useAuth();

  return useMutation({
    mutationFn: (input: CommentCreateInput) => commentService.add(requestId, input),
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: requestKeys.comments(requestId) });
      const previous = queryClient.getQueryData<CommentListPage>(requestKeys.comments(requestId));

      const optimisticComment: Comment = {
        id: `optimistic-${Date.now()}`,
        request_id: requestId,
        author_id: user?.id ?? "",
        parent_comment_id: input.parent_comment_id ?? null,
        body: input.body,
        deleted_at: null,
        deleted_by: null,
        created_at: new Date().toISOString(),
      };
      queryClient.setQueryData<CommentListPage | undefined>(
        requestKeys.comments(requestId),
        (old) => (old ? { ...old, data: [...old.data, optimisticComment] } : old),
      );

      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(requestKeys.comments(requestId), context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: requestKeys.comments(requestId) });
    },
  });
}
