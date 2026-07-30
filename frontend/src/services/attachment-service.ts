import { apiClient } from "@/lib/api/client";
import type { Attachment } from "@/types/attachment";

export const attachmentService = {
  list: (requestId: string) =>
    apiClient.getList<Attachment>(`/requests/${requestId}/attachments`),
  upload: (requestId: string, file: File) => {
    const formData = new FormData();
    formData.set("file", file);
    return apiClient.postForm<Attachment>(`/requests/${requestId}/attachments`, formData);
  },
  replace: (attachmentId: string, file: File) => {
    const formData = new FormData();
    formData.set("file", file);
    return apiClient.putForm<Attachment>(`/attachments/${attachmentId}`, formData);
  },
  remove: (attachmentId: string) => apiClient.delete<void>(`/attachments/${attachmentId}`),
  getDownloadUrl: (attachmentId: string) =>
    apiClient.get<{ url: string }>(`/attachments/${attachmentId}/download`),
};
