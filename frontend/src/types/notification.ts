/**
 * Frontend-owned types for the `/api/v1/notifications*` resource —
 * defined independently of the backend's Pydantic schemas, matching the
 * convention every other `types/*.ts` file in this project follows.
 */

export type NotificationType =
  | "assignment"
  | "reminder"
  | "escalation"
  | "decision"
  | "completion"
  | "system";

export interface Notification {
  id: string;
  recipient_id: string;
  request_id: string | null;
  notification_type: NotificationType;
  message: string;
  is_read: boolean;
  read_at: string | null;
  email_sent: boolean;
  email_sent_at: string | null;
  archived_at: string | null;
  is_archived: boolean;
  created_at: string;
}

export interface NotificationListFilters {
  is_read?: boolean;
  notification_type?: NotificationType;
  is_archived?: boolean;
  search?: string;
  page?: number;
  page_size?: number;
}

export interface NotificationPreference {
  notification_type: NotificationType;
  in_app_enabled: boolean;
  email_enabled: boolean;
  updated_at: string | null;
}

export interface NotificationPreferenceUpdate {
  in_app_enabled?: boolean;
  email_enabled?: boolean;
}
