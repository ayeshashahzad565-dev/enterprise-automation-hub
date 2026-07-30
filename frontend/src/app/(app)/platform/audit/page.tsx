"use client";

import { getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { Activity } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { DataTable } from "@/components/patterns/data-table/data-table";
import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { DataTableSkeleton } from "@/components/patterns/data-table/data-table-skeleton";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { buildPlatformAuditColumns } from "@/features/platform/components/platform-audit-columns";
import { useCompanies } from "@/features/platform/hooks/use-companies";
import { usePlatformAuditLog } from "@/features/platform/hooks/use-platform-audit-log";
import { ROUTES } from "@/utils/constants";

const COLUMN_COUNT = 5;

export default function PlatformAuditPage() {
  const searchParams = useSearchParams();
  const [companyId, setCompanyId] = useState(searchParams.get("company_id") ?? "");
  const [actorId, setActorId] = useState("");
  const [action, setAction] = useState("");
  const [createdAfter, setCreatedAfter] = useState("");
  const [createdBefore, setCreatedBefore] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const companiesQuery = useCompanies({ pageSize: 100 });
  const companies = companiesQuery.data?.data;
  const companyNamesById = useMemo(
    () => new Map((companies ?? []).map((company) => [company.id, company.name])),
    [companies],
  );

  const auditQuery = usePlatformAuditLog({
    company_id: companyId || undefined,
    actor_id: actorId.trim() || undefined,
    action: action || undefined,
    created_after: createdAfter ? new Date(createdAfter).toISOString() : undefined,
    created_before: createdBefore ? new Date(createdBefore).toISOString() : undefined,
    page,
    page_size: pageSize,
  });
  const entries = auditQuery.data?.data ?? [];

  const columns = buildPlatformAuditColumns(companyNamesById);
  const table = useReactTable({
    data: entries,
    columns,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });

  const hasFilter = Boolean(companyId || actorId || action || createdAfter || createdBefore);

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[{ label: "Platform", href: ROUTES.platform }, { label: "Audit" }]}
        title="Platform audit history"
        description="Every state-changing action across every tenant, filterable by company, actor, action, and date."
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="audit-company">Company</Label>
          <Select
            value={companyId || "all"}
            onValueChange={(value) => {
              setCompanyId(!value || value === "all" ? "" : value);
              setPage(1);
            }}
          >
            <SelectTrigger id="audit-company" size="sm" className="w-48">
              <SelectValue placeholder="All companies" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All companies</SelectItem>
              {(companies ?? []).map((company) => (
                <SelectItem key={company.id} value={company.id}>
                  {company.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-action">Action</Label>
          <Input
            id="audit-action"
            placeholder="e.g. COMPANY_SUSPENDED"
            className="h-8 w-52"
            value={action}
            onChange={(event) => {
              setAction(event.target.value);
              setPage(1);
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-actor">Actor id</Label>
          <Input
            id="audit-actor"
            placeholder="UUID"
            className="h-8 w-52"
            value={actorId}
            onChange={(event) => {
              setActorId(event.target.value);
              setPage(1);
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-after">After</Label>
          <Input
            id="audit-after"
            type="date"
            className="h-8"
            value={createdAfter}
            onChange={(event) => {
              setCreatedAfter(event.target.value);
              setPage(1);
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-before">Before</Label>
          <Input
            id="audit-before"
            type="date"
            className="h-8"
            value={createdBefore}
            onChange={(event) => {
              setCreatedBefore(event.target.value);
              setPage(1);
            }}
          />
        </div>
      </div>

      {auditQuery.isLoading ? (
        <DataTableSkeleton columnCount={COLUMN_COUNT} />
      ) : auditQuery.isError ? (
        <ErrorState message="Couldn't load the audit log." onRetry={() => auditQuery.refetch()} />
      ) : entries.length === 0 ? (
        <EmptyState
          icon={Activity}
          title={hasFilter ? "No matching audit entries" : "No audit entries yet"}
          description={hasFilter ? "Try a different filter." : "Platform activity will show up here."}
        />
      ) : (
        <>
          <DataTable table={table} />
          <DataTablePagination
            page={auditQuery.data?.pagination.page ?? 1}
            pageSize={auditQuery.data?.pagination.page_size ?? pageSize}
            totalRecords={auditQuery.data?.pagination.total_records ?? 0}
            totalPages={auditQuery.data?.pagination.total_pages ?? 1}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      )}
    </div>
  );
}
