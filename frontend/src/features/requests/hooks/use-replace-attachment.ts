"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { attachmentService } from "@/services/attachment-service";

export function useReplaceAttachment(requestId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ attachmentId, file }: { attachmentId: string; file: File }) =>
      attachmentService.replace(attachmentId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requestKeys.attachments(requestId) });
    },
  });
}
