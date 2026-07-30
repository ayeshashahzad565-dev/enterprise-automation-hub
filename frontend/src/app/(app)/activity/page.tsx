"use client";

import { Activity as ActivityIconLucide } from "lucide-react";
import { useState } from "react";

import { DataTablePagination } from "@/components/patterns/data-table/data-table-pagination";
import { DayGroupedList } from "@/components/patterns/day-grouped-list";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ActivityItem } from "@/features/activity/components/activity-item";
import {
  ActivityFiltersBar,
  EMPTY_ACTIVITY_FILTERS,
  type ActivityFilterState,
} from "@/features/activity/components/activity-filters-bar";
import { useMyActivity } from "@/features/activity/hooks/use-my-activity";
import { useOrganizationActivity } from "@/features/activity/hooks/use-organization-activity";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import type { ActivityListFilters, AuditLogEntry } from "@/types/activity";
import type { PaginationMeta } from "@/lib/api/types";

function toApiFilters(state: ActivityFilterState): Omit<ActivityListFilters, "actor_id"> {
  return {
    action: state.action || undefined,
    created_after: state.createdAfter || undefined,
    created_before: state.createdBefore || undefined,
  };
}

export default function ActivityPage() {
  const { data: profile } = useCurrentUser();
  const isAdmin = profile?.role === "admin";

  return (
    <div className="space-y-4">
      <PageHeader title="Activity" description="Everything happening across your requests and the organization." />

      <Tabs defaultValue="mine">
        <TabsList>
          <TabsTrigger value="mine">My Activity</TabsTrigger>
          <TabsTrigger value="organization">Organization</TabsTrigger>
        </TabsList>

        <TabsContent value="mine" className="space-y-4">
          <MyActivityTab />
        </TabsContent>

        <TabsContent value="organization" className="space-y-4">
          {isAdmin ? (
            <OrganizationActivityTab />
          ) : (
            <EmptyState
              icon={ActivityIconLucide}
              title="Admin-only"
              description="The organization-wide activity feed is visible to administrators only."
            />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Shared by both tabs below — previously each hand-rolled an identical
 * loading/error/empty/list/pagination body around its own query result. */
function ActivityFeedBody({
  isLoading,
  isError,
  onRetry,
  entries,
  pagination,
  pageSize,
  onPageChange,
  emptyDescription,
  onActorClick,
}: {
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  entries: AuditLogEntry[];
  pagination: PaginationMeta | undefined;
  pageSize: number;
  onPageChange: (page: number) => void;
  emptyDescription: string;
  onActorClick?: (actorId: string, actorName: string | null) => void;
}) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    );
  }
  if (isError) {
    return <ErrorState message="Couldn't load activity." onRetry={onRetry} />;
  }
  if (entries.length === 0) {
    return <EmptyState icon={ActivityIconLucide} title="No activity" description={emptyDescription} />;
  }
  return (
    <>
      <DayGroupedList
        items={entries}
        getKey={(entry) => entry.id}
        getDate={(entry) => entry.created_at}
        renderItem={(entry) => (
          <ActivityItem
            entry={entry}
            onActorClick={onActorClick ? (actorId) => onActorClick(actorId, entry.actor_name) : undefined}
          />
        )}
      />
      <DataTablePagination
        page={pagination?.page ?? 1}
        pageSize={pagination?.page_size ?? pageSize}
        totalRecords={pagination?.total_records ?? 0}
        totalPages={pagination?.total_pages ?? 1}
        onPageChange={onPageChange}
        onPageSizeChange={() => onPageChange(1)}
      />
    </>
  );
}

function MyActivityTab() {
  const [filters, setFilters] = useState<ActivityFilterState>(EMPTY_ACTIVITY_FILTERS);
  const [page, setPage] = useState(1);
  const apiFilters = toApiFilters(filters);
  const { data, isLoading, isError, refetch } = useMyActivity({ ...apiFilters, page, page_size: 20 });

  return (
    <div className="space-y-4">
      <ActivityFiltersBar
        value={filters}
        onChange={(next) => {
          setFilters(next);
          setPage(1);
        }}
      />
      <ActivityFeedBody
        isLoading={isLoading}
        isError={isError}
        onRetry={refetch}
        entries={data?.data ?? []}
        pagination={data?.pagination}
        pageSize={20}
        onPageChange={setPage}
        emptyDescription="Actions you take will show up here."
      />
    </div>
  );
}

function OrganizationActivityTab() {
  const [filters, setFilters] = useState<ActivityFilterState>(EMPTY_ACTIVITY_FILTERS);
  const [page, setPage] = useState(1);
  const apiFilters = toApiFilters(filters);
  const { data, isLoading, isError, refetch } = useOrganizationActivity({
    ...apiFilters,
    actor_id: filters.actorId,
    page,
    page_size: 20,
  });

  function handleActorClick(actorId: string, actorName: string | null) {
    setFilters((prev) => ({ ...prev, actorId, actorName: actorName ?? undefined }));
    setPage(1);
  }

  return (
    <div className="space-y-4">
      <ActivityFiltersBar
        value={filters}
        onChange={(next) => {
          setFilters(next);
          setPage(1);
        }}
      />
      <ActivityFeedBody
        isLoading={isLoading}
        isError={isError}
        onRetry={refetch}
        entries={data?.data ?? []}
        pagination={data?.pagination}
        pageSize={20}
        onPageChange={setPage}
        emptyDescription="No matching events."
        onActorClick={handleActorClick}
      />
    </div>
  );
}
