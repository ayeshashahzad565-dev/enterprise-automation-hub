"use client";

import { getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { Users as UsersIcon } from "lucide-react";
import { useState } from "react";

import { DataTable } from "@/components/patterns/data-table/data-table";
import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { DataTableSkeleton } from "@/components/patterns/data-table/data-table-skeleton";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { UserDetailPanel } from "@/features/admin/components/user-detail-panel";
import { UserDirectoryToolbar } from "@/features/admin/components/user-directory-toolbar";
import { useAdminUsers } from "@/features/admin/hooks/use-admin-users";
import type { AdminUser } from "@/types/admin";
import type { UserRole } from "@/types/profile";

const COLUMNS: ColumnDef<AdminUser>[] = [
  { accessorKey: "full_name", header: "Name" },
  {
    accessorKey: "role",
    header: "Role",
    cell: ({ row }) => <span className="capitalize">{row.original.role}</span>,
  },
  {
    accessorKey: "department",
    header: "Department",
    cell: ({ row }) => row.original.department ?? "—",
  },
  {
    accessorKey: "updated_at",
    header: "Updated",
    cell: ({ row }) => new Date(row.original.updated_at).toLocaleDateString(),
  },
];

export default function AdminUsersPage() {
  const [role, setRole] = useState<UserRole>("employee");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);

  const { data, isLoading, isError, refetch } = useAdminUsers({ role, query, page, pageSize });
  const rows = data?.data ?? [];

  const table = useReactTable({
    data: rows,
    columns: COLUMNS,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });

  const selectedUserForPanel = rows.find((u) => u.id === selectedUser?.id) ?? selectedUser;

  return (
    <div className="space-y-4">
      <PageHeader title="Users" description="Browse the directory, review profiles, and assign roles." />

      <UserDirectoryToolbar
        role={role}
        query={query}
        onRoleChange={(next) => {
          setRole(next);
          setPage(1);
        }}
        onQueryChange={(next) => {
          setQuery(next);
          setPage(1);
        }}
      />

      {isLoading ? (
        <DataTableSkeleton columnCount={COLUMNS.length} />
      ) : isError ? (
        <ErrorState message="Couldn't load the user directory." onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={UsersIcon}
          title="No users found"
          description={query ? "Try a different search term." : "No users in this role yet."}
        />
      ) : (
        <>
          <DataTable table={table} onRowClick={(user) => setSelectedUser(user)} />
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

      <UserDetailPanel
        user={selectedUserForPanel}
        open={selectedUser !== null}
        onOpenChange={(open) => !open && setSelectedUser(null)}
      />
    </div>
  );
}
