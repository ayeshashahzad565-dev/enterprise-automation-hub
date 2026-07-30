import { apiClient } from "@/lib/api/client";
import type { Comment, CommentCreateInput } from "@/types/comment";

export const commentService = {
  list: (requestId: string) => apiClient.getList<Comment>(`/requests/${requestId}/comments`),
  add: (requestId: string, input: CommentCreateInput) =>
    apiClient.post<Comment>(`/requests/${requestId}/comments`, input),
  remove: (commentId: string) => apiClient.delete<void>(`/comments/${commentId}`),
};
