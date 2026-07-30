"use client";

import { useParams, useRouter } from "next/navigation";

import { Breadcrumbs } from "@/components/patterns/breadcrumbs";
import { ErrorState } from "@/components/patterns/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ApprovalDetailContent } from "@/features/approvals/components/approval-detail-content";
import { useApprovalInbox } from "@/features/approvals/hooks/use-approval-inbox";
import { ROUTES } from "@/utils/constants";

/**
 * Deep-linkable full-page Approval Detail. There's no "get one pending
 * stage" backend endpoint (only the paginated inbox), so this resolves
 * `stageId` against the caller's own inbox (capped at 100, same bound
 * `/approval-eligibility` uses) — usually served straight from the
 * TanStack Query cache when arriving via a row click.
 */
export default function ApprovalDetailPage() {
  const params = useParams<{ stageId: string }>();
  const stageId = params.stageId;
  const router = useRouter();

  const inboxQuery = useApprovalInbox({ page_size: 100 });
  const item = inboxQuery.data?.data.find((row) => row.stage_id === stageId);

  return (
    <div className="space-y-2">
      <Breadcrumbs
        items={[
          { label: "Approvals", href: ROUTES.approvals },
          { label: item?.request_title ?? "Request" },
        ]}
      />

      {inboxQuery.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : inboxQuery.isError ? (
        <ErrorState message="Couldn't load your approval queue." onRetry={() => inboxQuery.refetch()} />
      ) : !item ? (
        <ErrorState message="This item is no longer in your approval queue." />
      ) : (
        <ApprovalDetailContent
          requestId={item.request_id}
          stageId={item.stage_id}
          stageVersion={item.stage_version}
          onDecided={() => router.push(ROUTES.approvals)}
        />
      )}
    </div>
  );
}
