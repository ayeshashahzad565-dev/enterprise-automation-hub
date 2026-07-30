"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { REQUEST_TYPES } from "@/features/requests/constants";

/** Search hits `search_definitions` (ILIKE on request_type); REQUEST_TYPES chips are quick filters onto the known, frontend-owned type list — the same "no request-type enumeration endpoint" constraint Analytics and Requests already accept. */
export function DefinitionListToolbar({
  search,
  onSearchChange,
  onQuickFilter,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  onQuickFilter: (requestType: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input
        value={search}
        onChange={(event) => onSearchChange(event.target.value)}
        placeholder="Search request types..."
        className="h-8 w-56"
      />
      {REQUEST_TYPES.map((type) => (
        <Button
          key={type.value}
          variant="outline"
          size="sm"
          className="h-8"
          onClick={() => onQuickFilter(type.value)}
        >
          {type.label}
        </Button>
      ))}
    </div>
  );
}
