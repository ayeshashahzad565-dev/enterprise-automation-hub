"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AuditAction } from "@/types/activity";

const ACTION_GROUPS: ReadonlyArray<{ label: string; actions: ReadonlyArray<{ value: AuditAction; label: string }> }> = [
  {
    label: "Request",
    actions: [
      { value: "REQUEST_CREATED", label: "Created" },
      { value: "REQUEST_WITHDRAWN", label: "Withdrawn" },
    ],
  },
  {
    label: "Approval",
    actions: [
      { value: "STAGE_APPROVED", label: "Approved" },
      { value: "STAGE_REJECTED", label: "Rejected" },
      { value: "STAGE_ESCALATED", label: "Escalated" },
    ],
  },
  {
    label: "Workflow",
    actions: [{ value: "WORKFLOW_DEFINITION_ACTIVATED", label: "Definition activated" }],
  },
  {
    label: "Comment",
    actions: [
      { value: "COMMENT_CREATED", label: "Added" },
      { value: "COMMENT_REMOVED", label: "Removed" },
    ],
  },
  {
    label: "Attachment",
    actions: [
      { value: "ATTACHMENT_UPLOADED", label: "Uploaded" },
      { value: "ATTACHMENT_REMOVED", label: "Removed" },
    ],
  },
  {
    label: "Profile",
    actions: [{ value: "PROFILE_UPDATED", label: "Updated" }],
  },
];

export interface ActivityFilterState {
  action: AuditAction | "";
  createdAfter: string;
  createdBefore: string;
  actorId?: string;
  actorName?: string;
}

export const EMPTY_ACTIVITY_FILTERS: ActivityFilterState = {
  action: "",
  createdAfter: "",
  createdBefore: "",
};

/**
 * Event-type filtering is a single exact `AuditAction` value (grouped
 * visually under category headings here for clarity) rather than a
 * category-wide filter — the backend's `list_all` only supports one
 * exact action per query.
 */
export function ActivityFiltersBar({
  value,
  onChange,
}: {
  value: ActivityFilterState;
  onChange: (next: ActivityFilterState) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={value.action || "all"}
        onValueChange={(next) => onChange({ ...value, action: next !== "all" ? (next as AuditAction) : "" })}
      >
        <SelectTrigger size="sm" className="w-48">
          <SelectValue placeholder="Event type" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All events</SelectItem>
          {ACTION_GROUPS.map((group) => (
            <SelectGroup key={group.label}>
              <SelectLabel>{group.label}</SelectLabel>
              {group.actions.map((action) => (
                <SelectItem key={action.value} value={action.value}>
                  {action.label}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
      <Input
        type="date"
        value={value.createdAfter}
        onChange={(event) => onChange({ ...value, createdAfter: event.target.value })}
        className="h-8 w-36"
        aria-label="From date"
      />
      <Input
        type="date"
        value={value.createdBefore}
        onChange={(event) => onChange({ ...value, createdBefore: event.target.value })}
        className="h-8 w-36"
        aria-label="To date"
      />
      {value.actorId && (
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1"
          onClick={() => onChange({ ...value, actorId: undefined, actorName: undefined })}
        >
          {value.actorName ?? "1 user"} ×
        </Button>
      )}
    </div>
  );
}
