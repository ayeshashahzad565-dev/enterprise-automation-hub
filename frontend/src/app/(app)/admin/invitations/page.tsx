"use client";

import { getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { Mail, Plus } from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CreateInvitationDialog } from "@/features/admin/components/create-invitation-dialog";
import { buildInvitationColumns } from "@/features/admin/components/invitation-columns";
import { useAdminInvitations } from "@/features/admin/hooks/use-admin-invitations";
import { useResendInvitation } from "@/features/admin/hooks/use-resend-invitation";
import { useRevokeInvitation } from "@/features/admin/hooks/use-revoke-invitation";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { Invitation, InvitationStatus } from "@/types/admin";

const STATUS_OPTIONS: ReadonlyArray<{ value: InvitationStatus; label: string }> = [
  { value: "pending", label: "Pending" },
  { value: "expired", label: "Expired" },
  { value: "accepted", label: "Accepted" },
  { value: "revoked", label: "Revoked" },
];

export default function AdminInvitationsPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<InvitationStatus | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<Invitation | null>(null);
  const [resendingId, setResendingId] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useAdminInvitations({
    status,
    query: search,
    page,
    pageSize,
  });
  const resendMutation = useResendInvitation();
  const revokeMutation = useRevokeInvitation();
  const rows = data?.data ?? [];

  async function handleResend(invitation: Invitation) {
    setResendingId(invitation.id);
    try {
      await resendMutation.mutateAsync(invitation.id);
      notifySuccess(`Invitation resent to ${invitation.email}.`);
    } catch (error) {
      notifyError(error, "Couldn't resend this invitation.");
    } finally {
      setResendingId(null);
    }
  }

  async function handleRevokeConfirm() {
    if (!revokeTarget) return;
    try {
      await revokeMutation.mutateAsync(revokeTarget.id);
      notifySuccess(`Invitation revoked for ${revokeTarget.email}.`);
    } catch (error) {
      notifyError(error, "Couldn't revoke this invitation.");
    } finally {
      setRevokeTarget(null);
    }
  }

  const columns = buildInvitationColumns({
    onResend: handleResend,
    onRevoke: (invitation) => setRevokeTarget(invitation),
    resendingId,
  });

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });

  const hasActiveFilter = Boolean(search || status);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Invitations"
        description="Invite new users and manage outstanding invitations."
        actions={
          <Button onClick={() => setCreateDialogOpen(true)}>
            <Plus className="size-4" /> New invitation
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
        searchPlaceholder="Search by name or email..."
        filters={
          <Select
            value={status ?? "all"}
            onValueChange={(value) => {
              setStatus(value === "all" ? undefined : (value as InvitationStatus));
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
      />

      {isLoading ? (
        <DataTableSkeleton columnCount={columns.length} />
      ) : isError ? (
        <ErrorState message="Couldn't load invitations." onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Mail}
          title={hasActiveFilter ? "No matching invitations" : "No invitations yet"}
          description={
            hasActiveFilter
              ? "Try a different search term or filter."
              : "Invite your first user to get started."
          }
          action={
            hasActiveFilter ? undefined : { label: "New invitation", onClick: () => setCreateDialogOpen(true) }
          }
        />
      ) : (
        <>
          <DataTable table={table} />
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

      <CreateInvitationDialog open={createDialogOpen} onOpenChange={setCreateDialogOpen} />

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        onOpenChange={(open) => !open && setRevokeTarget(null)}
        title="Revoke this invitation?"
        description={`${revokeTarget?.email ?? "This invitee"} will no longer be able to use their invitation link to join.`}
        confirmLabel="Revoke"
        isConfirming={revokeMutation.isPending}
        onConfirm={handleRevokeConfirm}
      />
    </div>
  );
}
