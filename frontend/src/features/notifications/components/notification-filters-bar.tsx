"use client";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { NotificationType } from "@/types/notification";

const TYPE_OPTIONS: ReadonlyArray<{ value: NotificationType; label: string }> = [
  { value: "assignment", label: "Assignment" },
  { value: "reminder", label: "Reminder" },
  { value: "escalation", label: "Escalation" },
  { value: "decision", label: "Decision" },
  { value: "completion", label: "Completion" },
  { value: "system", label: "System" },
];

export interface NotificationFilterState {
  status: "all" | "unread" | "read";
  notificationType: NotificationType | "";
  archived: boolean;
  search: string;
}

export const EMPTY_NOTIFICATION_FILTERS: NotificationFilterState = {
  status: "all",
  notificationType: "",
  archived: false,
  search: "",
};

/** Status/type/archived selects plus a free-text search field. The
 * search value is debounced by the page and sent to the backend's
 * `GET /notifications?search=` param — matched server-side, across
 * every page, not just the currently-loaded one. */
export function NotificationFiltersBar({
  value,
  onChange,
}: {
  value: NotificationFilterState;
  onChange: (next: NotificationFilterState) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input
        value={value.search}
        onChange={(event) => onChange({ ...value, search: event.target.value })}
        placeholder="Search notifications..."
        className="h-8 w-56"
      />
      <Select
        value={value.status}
        onValueChange={(next) => onChange({ ...value, status: next as NotificationFilterState["status"] })}
      >
        <SelectTrigger size="sm" className="w-32">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All</SelectItem>
          <SelectItem value="unread">Unread</SelectItem>
          <SelectItem value="read">Read</SelectItem>
        </SelectContent>
      </Select>
      <Select
        value={value.notificationType || "all"}
        onValueChange={(next) =>
          onChange({ ...value, notificationType: next !== "all" ? (next as NotificationType) : "" })
        }
      >
        <SelectTrigger size="sm" className="w-36">
          <SelectValue placeholder="Type" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All types</SelectItem>
          {TYPE_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={value.archived ? "archived" : "active"}
        onValueChange={(next) => onChange({ ...value, archived: next === "archived" })}
      >
        <SelectTrigger size="sm" className="w-32">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="active">Active</SelectItem>
          <SelectItem value="archived">Archived</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
