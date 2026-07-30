"use client";

import { getCoreRowModel, getSortedRowModel, useReactTable } from "@tanstack/react-table";
import type { RowSelectionState, SortingState } from "@tanstack/react-table";
import { Inbox } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable, usePersistedColumnVisibility } from "@/components/patterns/data-table/data-table";
import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { DataTableSkeleton } from "@/components/patterns/data-table/data-table-skeleton";
import { ConfirmDialog } from "@/components/patterns/confirm-dialog";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApprovalInboxToolbar } from "@/features/approvals/components/approval-inbox-toolbar";
import { ApprovalDetailContent } from "@/features/approvals/components/approval-detail-content";
import { ApprovalPreviewSheet } from "@/features/approvals/components/approval-preview-sheet";
import { buildApprovalColumns } from "@/features/approvals/components/approval-columns";
import { BulkActionBar } from "@/features/approvals/components/bulk-action-bar";
import { DecisionDialog, type DecisionAction } from "@/features/approvals/components/decision-dialog";
import { useApprovalInbox } from "@/features/approvals/hooks/use-approval-inbox";
import { useApprovalKeyboardNav } from "@/features/approvals/hooks/use-approval-keyboard-nav";
import { useApproveStage } from "@/features/approvals/hooks/use-approve-stage";
import { useBulkApprove } from "@/features/approvals/hooks/use-bulk-approve";
import { useBulkReject } from "@/features/approvals/hooks/use-bulk-reject";
import { useRejectStage } from "@/features/approvals/hooks/use-reject-stage";
import { useSavedViews } from "@/features/approvals/hooks/use-saved-views";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { ApprovalInboxItem, BulkDecisionResultItem } from "@/types/approval";

export default function ApprovalsInboxPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [requestTypeFilter, setRequestTypeFilter] = useState<string | undefined>(undefined);
  const [departmentFilter, setDepartmentFilter] = useState<string | undefined>(undefined);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [viewMode, setViewMode] = useState<"table" | "split">("table");
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [decisionTarget, setDecisionTarget] = useState<{
    item: ApprovalInboxItem;
    action: DecisionAction;
  } | null>(null);
  const [bulkApproveConfirmOpen, setBulkApproveConfirmOpen] = useState(false);
  const [bulkRejectOpen, setBulkRejectOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);

  const [columnVisibility, onColumnVisibilityChange] = usePersistedColumnVisibility(
    "eah:approvals-column-visibility",
  );
  const { views, saveView, removeView } = useSavedViews();

  const params = useMemo(() => ({ page, page_size: pageSize }), [page, pageSize]);
  const { data, isLoading, isError, refetch } = useApprovalInbox(params);

  const approveStage = useApproveStage();
  const rejectStage = useRejectStage();
  const bulkApprove = useBulkApprove();
  const bulkReject = useBulkReject();

  const rows = useMemo(() => data?.data ?? [], [data]);
  const requestTypeOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.request_type))),
    [rows],
  );
  const departmentOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.department).filter((d): d is string => Boolean(d)))),
    [rows],
  );

  const filteredRows = useMemo(() => {
    return rows.filter((row) => {
      if (requestTypeFilter && row.request_type !== requestTypeFilter) return false;
      if (departmentFilter && row.department !== departmentFilter) return false;
      if (search && !row.request_title.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [rows, requestTypeFilter, departmentFilter, search]);

  const columns = useMemo(
    () =>
      buildApprovalColumns({
        onApprove: (item) => setDecisionTarget({ item, action: "approve" }),
        onReject: (item) => setDecisionTarget({ item, action: "reject" }),
      }),
    [],
  );

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting, columnVisibility, rowSelection },
    getRowId: (row) => row.stage_id,
    onSortingChange: setSorting,
    onColumnVisibilityChange,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: true,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const selectedItems = filteredRows.filter((row) => rowSelection[row.stage_id]);
  const selectedItem = filteredRows.find((row) => row.stage_id === selectedStageId) ?? null;
  const previewItem = selectedItem
    ? {
        stageId: selectedItem.stage_id,
        requestId: selectedItem.request_id,
        stageVersion: selectedItem.stage_version,
        requestTitle: selectedItem.request_title,
      }
    : null;

  function handleRowClick(row: ApprovalInboxItem) {
    setSelectedStageId(row.stage_id);
    setFocusedIndex(filteredRows.findIndex((candidate) => candidate.stage_id === row.stage_id));
    if (viewMode === "table") setPreviewOpen(true);
  }

  const isOverlayOpen =
    previewOpen || Boolean(decisionTarget) || bulkRejectOpen || bulkApproveConfirmOpen;

  useApprovalKeyboardNav({
    rowCount: filteredRows.length,
    focusedIndex,
    onFocusChange: setFocusedIndex,
    onOpen: (index) => handleRowClick(filteredRows[index]),
    onApprove: (index) => setDecisionTarget({ item: filteredRows[index], action: "approve" }),
    onReject: (index) => setDecisionTarget({ item: filteredRows[index], action: "reject" }),
    onToggleSplitView: () => setViewMode((mode) => (mode === "table" ? "split" : "table")),
    enabled: !isOverlayOpen,
  });

  function reportBulkResult(results: BulkDecisionResultItem[], verb: "approved" | "rejected") {
    const succeeded = results.filter((result) => result.success).length;
    const failed = results.length - succeeded;
    const label = verb === "approved" ? "Approved" : "Rejected";
    if (failed === 0) {
      toast.success(`${label} ${succeeded} request${succeeded === 1 ? "" : "s"}.`);
    } else {
      toast.error(`${succeeded} ${verb}, ${failed} failed.`);
    }
  }

  async function handleDecisionSubmit(note: string | undefined) {
    if (!decisionTarget) return;
    const { item, action } = decisionTarget;
    try {
      if (action === "approve") {
        await approveStage.mutateAsync({
          stageId: item.stage_id,
          input: { expected_version: item.stage_version, decision_note: note },
        });
        notifySuccess("Request approved.");
      } else {
        await rejectStage.mutateAsync({
          stageId: item.stage_id,
          input: { expected_version: item.stage_version, decision_note: note ?? "" },
        });
        notifySuccess(action === "reject" ? "Request rejected." : "Changes requested.");
      }
    } catch (error) {
      notifyError(error, "Couldn't complete this action.");
    } finally {
      setDecisionTarget(null);
    }
  }

  async function handleBulkApproveConfirm() {
    const items = selectedItems.map((row) => ({
      stage_id: row.stage_id,
      expected_version: row.stage_version,
    }));
    try {
      const result = await bulkApprove.mutateAsync(items);
      reportBulkResult(result.results, "approved");
    } catch (error) {
      notifyError(error, "Couldn't process the bulk approval.");
    } finally {
      setRowSelection({});
      setBulkApproveConfirmOpen(false);
    }
  }

  async function handleBulkRejectSubmit(note: string | undefined) {
    const items = selectedItems.map((row) => ({
      stage_id: row.stage_id,
      expected_version: row.stage_version,
      decision_note: note,
    }));
    try {
      const result = await bulkReject.mutateAsync(items);
      reportBulkResult(result.results, "rejected");
    } catch (error) {
      notifyError(error, "Couldn't process the bulk rejection.");
    } finally {
      setRowSelection({});
      setBulkRejectOpen(false);
    }
  }

  const hasActiveFilter = Boolean(search || requestTypeFilter || departmentFilter);
  const isSubmittingDecision = approveStage.isPending || rejectStage.isPending;

  return (
    <div className="space-y-4">
      <PageHeader title="Approvals" description="Requests waiting on your decision." />

      <ApprovalInboxToolbar
        table={table}
        searchValue={search}
        onSearchChange={setSearch}
        filters={
          <div className="flex items-center gap-2">
            <Select
              value={requestTypeFilter ?? "all"}
              onValueChange={(value) => setRequestTypeFilter(value && value !== "all" ? value : undefined)}
            >
              <SelectTrigger size="sm" className="w-40">
                <SelectValue placeholder="Type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All types</SelectItem>
                {requestTypeOptions.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={departmentFilter ?? "all"}
              onValueChange={(value) => setDepartmentFilter(value && value !== "all" ? value : undefined)}
            >
              <SelectTrigger size="sm" className="w-40">
                <SelectValue placeholder="Department" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All departments</SelectItem>
                {departmentOptions.map((department) => (
                  <SelectItem key={department} value={department}>
                    {department}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        }
        savedViews={views}
        onApplyView={(view) => {
          setRequestTypeFilter(view.requestType);
          setDepartmentFilter(view.department);
          onColumnVisibilityChange(view.columnVisibility);
        }}
        onSaveCurrentView={(name) =>
          saveView({ name, requestType: requestTypeFilter, department: departmentFilter, columnVisibility })
        }
        onRemoveView={removeView}
        viewMode={viewMode}
        onToggleViewMode={() => setViewMode((mode) => (mode === "table" ? "split" : "table"))}
        bulkActions={
          <BulkActionBar
            selectedCount={selectedItems.length}
            isSubmitting={bulkApprove.isPending || bulkReject.isPending}
            onApprove={() => setBulkApproveConfirmOpen(true)}
            onReject={() => setBulkRejectOpen(true)}
            onClear={() => setRowSelection({})}
          />
        }
      />

      {isLoading ? (
        <DataTableSkeleton columnCount={columns.length} />
      ) : isError ? (
        <ErrorState message="Couldn't load your approval queue." onRetry={() => refetch()} />
      ) : filteredRows.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title={hasActiveFilter ? "No matching approvals" : "You're all caught up"}
          description={
            hasActiveFilter
              ? "Try a different search term or filter."
              : "Nothing is waiting on your decision right now."
          }
        />
      ) : viewMode === "split" ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="space-y-4">
            <DataTable table={table} onRowClick={handleRowClick} emptyMessage="No pending approvals." />
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
          </div>
          <div className="rounded-lg border">
            {selectedItem ? (
              <div className="p-4">
                <ApprovalDetailContent
                  requestId={selectedItem.request_id}
                  stageId={selectedItem.stage_id}
                  stageVersion={selectedItem.stage_version}
                  onDecided={() => setSelectedStageId(null)}
                />
              </div>
            ) : (
              <div className="p-6">
                <EmptyState
                  icon={Inbox}
                  title="Select a request"
                  description="Choose a row on the left to preview it here."
                />
              </div>
            )}
          </div>
        </div>
      ) : (
        <>
          <DataTable table={table} onRowClick={handleRowClick} emptyMessage="No pending approvals." />
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

      <ApprovalPreviewSheet
        item={previewItem}
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        onDecided={() => refetch()}
      />

      {decisionTarget && (
        <DecisionDialog
          open={Boolean(decisionTarget)}
          onOpenChange={(open) => !open && setDecisionTarget(null)}
          action={decisionTarget.action}
          isSubmitting={isSubmittingDecision}
          onSubmit={handleDecisionSubmit}
        />
      )}

      <ConfirmDialog
        open={bulkApproveConfirmOpen}
        onOpenChange={setBulkApproveConfirmOpen}
        title={`Approve ${selectedItems.length} request${selectedItems.length === 1 ? "" : "s"}?`}
        description="Each item is approved independently — a stale or already-decided item won't block the rest."
        confirmLabel="Approve"
        destructive={false}
        isConfirming={bulkApprove.isPending}
        onConfirm={handleBulkApproveConfirm}
      />

      <DecisionDialog
        open={bulkRejectOpen}
        onOpenChange={setBulkRejectOpen}
        action="reject"
        isSubmitting={bulkReject.isPending}
        onSubmit={handleBulkRejectSubmit}
      />
    </div>
  );
}
