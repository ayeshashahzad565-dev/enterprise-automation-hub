"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { attachmentService } from "@/services/attachment-service";

export function useUploadAttachment(requestId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => attachmentService.upload(requestId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requestKeys.attachments(requestId) });
    },
  });
}
