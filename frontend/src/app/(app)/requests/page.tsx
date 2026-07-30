"use client";

import { getCoreRowModel, getSortedRowModel, useReactTable } from "@tanstack/react-table";
import type { RowSelectionState, SortingState } from "@tanstack/react-table";
import { FileText, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/patterns/confirm-dialog";
import { DataTable, usePersistedColumnVisibility } from "@/components/patterns/data-table/data-table";
import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { DataTableSkeleton } from "@/components/patterns/data-table/data-table-skeleton";
import { DataTableToolbar } from "@/components/patterns/data-table/data-table-toolbar";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import { buildRequestColumns } from "@/features/requests/components/request-columns";
import { useRequests } from "@/features/requests/hooks/use-requests";
import { useWithdrawRequest } from "@/features/requests/hooks/use-withdraw-request";
import { notifyError, notifySuccess } from "@/lib/toast";
import { useAuth } from "@/providers/auth-provider";
import type { Request, RequestStatus } from "@/types/request";
import { ROUTES } from "@/utils/constants";

const STATUS_OPTIONS: ReadonlyArray<{ value: RequestStatus; label: string }> = [
  { value: "pending", label: "Pending" },
  { value: "in_review", label: "In review" },
  { value: "rejected", label: "Rejected" },
  { value: "completed", label: "Completed" },
];

function isRequestStatus(value: string | null): value is RequestStatus {
  return STATUS_OPTIONS.some((option) => option.value === value);
}

export default function RequestsListPage() {
  return (
    <Suspense fallback={<DataTableSkeleton columnCount={7} />}>
      <RequestsListPageContent />
    </Suspense>
  );
}

function RequestsListPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState("");
  // Supports drill-down from Analytics' status-breakdown chart (`/requests?status=pending`).
  const [status, setStatus] = useState<RequestStatus | undefined>(() => {
    const initial = searchParams.get("status");
    return isRequestStatus(initial) ? initial : undefined;
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [withdrawTarget, setWithdrawTarget] = useState<Request | null>(null);
  const [sorting, setSorting] = useState<SortingState>([]);

  const { user } = useAuth();
  const { data: profile } = useCurrentUser();

  const params = useMemo(
    () => ({ search: search || undefined, status, page, page_size: pageSize }),
    [search, status, page, pageSize],
  );

  const { data, isLoading, isError, refetch } = useRequests(params);
  const withdrawMutation = useWithdrawRequest();
  const [columnVisibility, onColumnVisibilityChange] = usePersistedColumnVisibility(
    "eah:requests-column-visibility",
  );

  function canEdit(request: Request): boolean {
    return !request.deleted_at && request.status === "pending" && request.requester_id === user?.id;
  }

  function canWithdraw(request: Request): boolean {
    if (request.deleted_at) return false;
    if (profile?.role === "admin") return true;
    return request.status === "pending" && request.requester_id === user?.id;
  }

  const columns = useMemo(
    () =>
      buildRequestColumns({
        canEdit,
        canWithdraw,
        onWithdraw: (request) => setWithdrawTarget(request),
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [profile?.role, user?.id],
  );

  const table = useReactTable({
    data: data?.data ?? [],
    columns,
    state: { sorting, columnVisibility, rowSelection },
    getRowId: (row) => row.id,
    onSortingChange: setSorting,
    onColumnVisibilityChange,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: true,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const selectedRequests = (data?.data ?? []).filter((request) => rowSelection[request.id]);
  const withdrawableSelected = selectedRequests.filter(canWithdraw);

  async function handleBulkWithdraw() {
    let succeeded = 0;
    let failed = 0;
    for (const request of withdrawableSelected) {
      try {
        await withdrawMutation.mutateAsync({ id: request.id, expectedVersion: request.version });
        succeeded += 1;
      } catch {
        failed += 1;
      }
    }
    setRowSelection({});
    if (failed === 0) {
      notifySuccess(`Withdrew ${succeeded} request${succeeded === 1 ? "" : "s"}.`);
    } else {
      toast.error(`Withdrew ${succeeded}, ${failed} failed.`);
    }
  }

  async function handleWithdrawConfirm() {
    if (!withdrawTarget) return;
    try {
      await withdrawMutation.mutateAsync({
        id: withdrawTarget.id,
        expectedVersion: withdrawTarget.version,
      });
      notifySuccess("Request withdrawn.");
    } catch (error) {
      notifyError(error, "Couldn't withdraw this request.");
    } finally {
      setWithdrawTarget(null);
    }
  }

  const hasActiveFilter = Boolean(search || status);
  const rows = data?.data ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Requests"
        actions={
          <Button render={<Link href={ROUTES.newRequest} />}>
            <Plus className="size-4" /> New request
          </Button>
        }
      />

      <DataTableToolbar
        table={table}
        searchValue={search}
        onSearchChange={(value) => {
          setSearch(value);
          setPage(1);
        }}
        searchPlaceholder="Search requests..."
        filtersDisabled={Boolean(search)}
        filtersDisabledReason="Clear the search to use filters — they can't be combined yet."
        filters={
          <Select
            value={status ?? "all"}
            onValueChange={(value) => {
              setStatus(value === "all" ? undefined : (value as RequestStatus));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-40">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {STATUS_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
        primaryAction={
          selectedRequests.length > 0 ? (
            <Button
              variant="destructive"
              size="sm"
              disabled={withdrawableSelected.length === 0 || withdrawMutation.isPending}
              onClick={handleBulkWithdraw}
            >
              Withdraw {withdrawableSelected.length} selected
            </Button>
          ) : undefined
        }
      />

      {isLoading ? (
        <DataTableSkeleton columnCount={columns.length} />
      ) : isError ? (
        <ErrorState message="Couldn't load requests." onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={FileText}
          title={hasActiveFilter ? "No matching requests" : "No requests yet"}
          description={
            hasActiveFilter
              ? "Try a different search term or filter."
              : "Create your first request to get started."
          }
          action={
            hasActiveFilter
              ? undefined
              : { label: "New request", onClick: () => router.push(ROUTES.newRequest) }
          }
        />
      ) : (
        <>
          <DataTable table={table} onRowClick={(request) => router.push(ROUTES.request(request.id))} />
          <DataTablePagination
            page={data?.pagination.page ?? 1}
            pageSize={data?.pagination.page_size ?? pageSize}
            totalRecords={data?.pagination.total_records ?? 0}
            totalPages={data?.pagination.total_pages ?? 1}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      )}

      <ConfirmDialog
        open={Boolean(withdrawTarget)}
        onOpenChange={(open) => !open && setWithdrawTarget(null)}
        title="Withdraw this request?"
        description="This can't be undone. The request will be removed from your active list."
        confirmLabel="Withdraw"
        isConfirming={withdrawMutation.isPending}
        onConfirm={handleWithdrawConfirm}
      />
    </div>
  );
}
