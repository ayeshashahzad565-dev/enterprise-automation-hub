"use client";

import { formatRelativeTime } from "@/lib/format-relative-time";
import { getAuditActionMeta } from "@/features/platform/lib/audit-action-meta";
import type { PlatformAuditEntry } from "@/types/platform";

/** Shared row renderer for the platform overview's activity timeline and
 * the company detail page's company-scoped activity slice — the only
 * difference between the two call sites is whether a company name is
 * resolved and shown per row (the overview spans every tenant; the
 * detail page is already scoped to one company, so showing its own name
 * on every row would be redundant). `companyNamesById` is a `Map` built
 * from the companies list's own query cache — there is no server-side
 * join for this (see `PlatformAuditEntryOut`'s own docstring), so this is
 * resolved client-side, never via a second backend call. */
export function PlatformActivityList({
  entries,
  companyNamesById,
}: {
  entries: PlatformAuditEntry[];
  companyNamesById?: Map<string, string>;
}) {
  return (
    <div className="space-y-1">
      {entries.map((entry) => {
        const meta = getAuditActionMeta(entry.action);
        const Icon = meta.icon;
        const companyName = entry.company_id ? companyNamesById?.get(entry.company_id) : undefined;
        return (
          <div key={entry.id} className="flex items-start gap-3 rounded-md px-3 py-2 text-sm">
            <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            <div className="min-w-0 flex-1 space-y-0.5">
              <p className="font-medium">{meta.label}</p>
              <p className="text-xs text-muted-foreground">
                {companyName ?? (entry.company_id ? "Unknown company" : "Platform-level")}
                {" · "}
                {formatRelativeTime(entry.created_at)}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
