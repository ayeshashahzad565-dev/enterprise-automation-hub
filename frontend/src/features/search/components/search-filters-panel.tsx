"use client";

import { getSearchEntityMeta } from "@/features/search/components/search-result-icon";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { SearchEntityType } from "@/types/search";

/** "user"/"department" results are admin-only server-side (a non-admin's
 * search simply omits them) — hiding the filter for a non-admin avoids
 * offering a toggle that would visibly do nothing. */
const ALL_ENTITY_TYPES: SearchEntityType[] = [
  "request",
  "approval",
  "workflow",
  "comment",
  "attachment",
  "notification",
  "audit_entry",
  "user",
  "department",
];
const ADMIN_ONLY_TYPES: ReadonlySet<SearchEntityType> = new Set(["user", "department"]);

export function SearchFiltersPanel({
  selected,
  onChange,
  isAdmin,
}: {
  selected: SearchEntityType[];
  onChange: (types: SearchEntityType[]) => void;
  isAdmin: boolean;
}) {
  const visibleTypes = ALL_ENTITY_TYPES.filter((type) => isAdmin || !ADMIN_ONLY_TYPES.has(type));

  function toggle(type: SearchEntityType, checked: boolean) {
    onChange(checked ? [...selected, type] : selected.filter((t) => t !== type));
  }

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <p className="text-xs font-medium text-muted-foreground">Search in</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {visibleTypes.map((type) => {
          const { label } = getSearchEntityMeta(type);
          const id = `search-filter-${type}`;
          return (
            <div key={type} className="flex items-center gap-2">
              <Checkbox
                id={id}
                checked={selected.includes(type)}
                onCheckedChange={(checked) => toggle(type, checked === true)}
              />
              <Label htmlFor={id} className="text-sm font-normal">
                {label}
              </Label>
            </div>
          );
        })}
      </div>
    </div>
  );
}
