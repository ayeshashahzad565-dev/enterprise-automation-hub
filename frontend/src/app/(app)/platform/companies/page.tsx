"use client";

import { getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { Building2, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/patterns/confirm-dialog";
import { DataTable } from "@/components/patterns/data-table/data-table";
import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { DataTableSkeleton } from "@/components/patterns/data-table/data-table-skeleton";
import { DataTableToolbar } from "@/components/patterns/data-table/data-table-toolbar";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { CreateCompanyDialog } from "@/features/platform/components/create-company-dialog";
import { buildCompanyColumns } from "@/features/platform/components/company-columns";
import { useCompanies } from "@/features/platform/hooks/use-companies";
import { useDeleteCompany } from "@/features/platform/hooks/use-delete-company";
import { useRestoreCompany } from "@/features/platform/hooks/use-restore-company";
import { useUpdateCompany } from "@/features/platform/hooks/use-update-company";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { Company } from "@/types/platform";
import { ROUTES } from "@/utils/constants";

const COLUMN_COUNT = 6;

export default function PlatformCompaniesPage() {
  const router = useRouter();
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [createOpen, setCreateOpen] = useState(false);
  const [suspendTarget, setSuspendTarget] = useState<Company | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Company | null>(null);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const companiesQuery = useCompanies({ includeDeleted, page, pageSize });
  const updateCompany = useUpdateCompany();
  const deleteCompany = useDeleteCompany();
  const restoreCompany = useRestoreCompany();

  const allCompanies = companiesQuery.data?.data ?? [];
  // Client-side only, over the currently-loaded page: `GET /platform/companies`
  // has no `search` query param, and the companies list is small enough
  // (platform-admin-only, one row per tenant) that adding server-side
  // search isn't warranted for this baseline.
  const needle = search.trim().toLowerCase();
  const companies = needle
    ? allCompanies.filter(
        (company) =>
          company.name.toLowerCase().includes(needle) ||
          company.slug.toLowerCase().includes(needle) ||
          (company.contact_email ?? "").toLowerCase().includes(needle),
      )
    : allCompanies;

  async function handleReactivate(company: Company) {
    setWorkingId(company.id);
    try {
      await updateCompany.mutateAsync({
        id: company.id,
        body: { expected_version: company.version, is_active: true },
      });
      notifySuccess(`${company.name} reactivated.`);
    } catch (error) {
      notifyError(error, "Couldn't reactivate this company.");
    } finally {
      setWorkingId(null);
    }
  }

  async function handleSuspendConfirm() {
    if (!suspendTarget) return;
    setWorkingId(suspendTarget.id);
    try {
      await updateCompany.mutateAsync({
        id: suspendTarget.id,
        body: { expected_version: suspendTarget.version, is_active: false },
      });
      notifySuccess(`${suspendTarget.name} suspended.`);
    } catch (error) {
      notifyError(error, "Couldn't suspend this company.");
    } finally {
      setWorkingId(null);
      setSuspendTarget(null);
    }
  }

  async function handleDeleteConfirm() {
    if (!deleteTarget) return;
    setWorkingId(deleteTarget.id);
    try {
      await deleteCompany.mutateAsync({ id: deleteTarget.id, expectedVersion: deleteTarget.version });
      notifySuccess(`${deleteTarget.name} deleted.`);
    } catch (error) {
      notifyError(error, "Couldn't delete this company.");
    } finally {
      setWorkingId(null);
      setDeleteTarget(null);
    }
  }

  async function handleRestore(company: Company) {
    setWorkingId(company.id);
    try {
      await restoreCompany.mutateAsync({ id: company.id, expectedVersion: company.version });
      notifySuccess(`${company.name} restored.`);
    } catch (error) {
      notifyError(error, "Couldn't restore this company.");
    } finally {
      setWorkingId(null);
    }
  }

  const columns = buildCompanyColumns({
    onSuspend: setSuspendTarget,
    onReactivate: handleReactivate,
    onDelete: setDeleteTarget,
    onRestore: handleRestore,
    workingId,
  });
  const table = useReactTable({
    data: companies,
    columns,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[{ label: "Platform", href: "/platform" }, { label: "Companies" }]}
        title="Companies"
        description="Every tenant on the platform — create, suspend, delete, and restore."
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" /> New company
          </Button>
        }
      />

      <div className="flex items-center gap-2">
        <Checkbox
          id="include-deleted"
          checked={includeDeleted}
          onCheckedChange={(checked) => {
            setIncludeDeleted(checked === true);
            setPage(1);
          }}
        />
        <Label htmlFor="include-deleted" className="text-sm font-normal">
          Include deleted companies
        </Label>
      </div>

      <DataTableToolbar
        table={table}
        searchValue={search}
        onSearchChange={setSearch}
        searchPlaceholder="Filter loaded companies by name, slug, or email..."
      />

      {companiesQuery.isLoading ? (
        <DataTableSkeleton columnCount={COLUMN_COUNT} />
      ) : companiesQuery.isError ? (
        <ErrorState message="Couldn't load companies." onRetry={() => companiesQuery.refetch()} />
      ) : companies.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No companies yet"
          description="Create the first tenant to get started."
        />
      ) : (
        <>
          <DataTable table={table} onRowClick={(company) => router.push(ROUTES.platformCompany(company.id))} />
          <DataTablePagination
            page={companiesQuery.data?.pagination.page ?? 1}
            pageSize={companiesQuery.data?.pagination.page_size ?? pageSize}
            totalRecords={companiesQuery.data?.pagination.total_records ?? 0}
            totalPages={companiesQuery.data?.pagination.total_pages ?? 1}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      )}

      <CreateCompanyDialog open={createOpen} onOpenChange={setCreateOpen} />

      <ConfirmDialog
        open={Boolean(suspendTarget)}
        onOpenChange={(open) => !open && setSuspendTarget(null)}
        title="Suspend this company?"
        description={`Every user in ${suspendTarget?.name ?? "this company"} will be signed out on their next request. You can reactivate at any time.`}
        confirmLabel="Suspend"
        isConfirming={updateCompany.isPending}
        onConfirm={handleSuspendConfirm}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete this company?"
        description={`${deleteTarget?.name ?? "This company"} and every user in it will lose access immediately. All data is retained and this can be reversed via Restore.`}
        confirmLabel="Delete"
        isConfirming={deleteCompany.isPending}
        onConfirm={handleDeleteConfirm}
      />
    </div>
  );
}
