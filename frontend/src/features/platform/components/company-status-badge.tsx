"use client";

import { Archive, Check, Power } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { Company } from "@/types/platform";

/** A company's status is derived from two independent fields
 * (`is_deleted`/`is_active`), not a single enum column — soft-deleted
 * takes visual precedence since a deleted company is also, incidentally,
 * inactive. */
export function CompanyStatusBadge({ company }: { company: Pick<Company, "is_active" | "is_deleted"> }) {
  if (company.is_deleted) {
    return (
      <Badge variant="status-withdrawn">
        <Archive /> Deleted
      </Badge>
    );
  }
  if (!company.is_active) {
    return (
      <Badge variant="status-rejected">
        <Power /> Suspended
      </Badge>
    );
  }
  return (
    <Badge variant="status-completed">
      <Check /> Active
    </Badge>
  );
}
