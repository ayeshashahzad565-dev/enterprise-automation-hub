import { apiClient } from "@/lib/api/client";
import type {
  Notification,
  NotificationListFilters,
  NotificationPreference,
  NotificationPreferenceUpdate,
} from "@/types/notification";

function buildQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const notificationService = {
  list: (filters: NotificationListFilters = {}) =>
    apiClient.getList<Notification>(`/notifications${buildQuery(filters)}`),
  getUnreadCount: () => apiClient.get<{ unread_count: number }>("/notifications/unread-count"),
  markRead: (id: string) => apiClient.post<Notification>(`/notifications/${id}/read`),
  markAllRead: () => apiClient.post<{ updated: number }>("/notifications/read-all"),
  archive: (id: string) => apiClient.post<Notification>(`/notifications/${id}/archive`),
  unarchive: (id: string) => apiClient.post<Notification>(`/notifications/${id}/unarchive`),
  getPreferences: () => apiClient.get<NotificationPreference[]>("/notifications/preferences"),
  updatePreference: (notificationType: string, body: NotificationPreferenceUpdate) =>
    apiClient.patch<NotificationPreference>(
      `/notifications/preferences/${notificationType}`,
      body,
    ),
};
