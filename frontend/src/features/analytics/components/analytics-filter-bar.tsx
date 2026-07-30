"use client";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { REQUEST_TYPES } from "@/features/requests/constants";

export interface AnalyticsFilterState {
  department: string;
  requestType: string;
  createdAfter: string;
  createdBefore: string;
}

export const EMPTY_ANALYTICS_FILTERS: AnalyticsFilterState = {
  department: "",
  requestType: "",
  createdAfter: "",
  createdBefore: "",
};

/** Department/type/date-range filters, shared by the Executive, Operational, and Explorer tabs. */
export function AnalyticsFilterBar({
  value,
  onChange,
}: {
  value: AnalyticsFilterState;
  onChange: (next: AnalyticsFilterState) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Input
        value={value.department}
        onChange={(event) => onChange({ ...value, department: event.target.value })}
        placeholder="Department..."
        className="h-8 w-40"
      />
      {/* size="default" (h-8), not "sm" (h-7) — the Input/Button controls
       * in this row are all h-8, and "sm" here was the one control a few
       * pixels shorter than everything beside it. */}
      <Select
        value={value.requestType || "all"}
        onValueChange={(next) => onChange({ ...value, requestType: next && next !== "all" ? next : "" })}
      >
        <SelectTrigger className="h-8 w-44">
          <SelectValue placeholder="Request type" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All types</SelectItem>
          {REQUEST_TYPES.map((type) => (
            <SelectItem key={type.value} value={type.value}>
              {type.label}
            </SelectItem>
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
    </div>
  );
}
