"use client";

import { ArrowRight, BarChart3, CheckSquare, Clock, FileText, Inbox, Plus } from "lucide-react";
import Link from "next/link";

import { KpiRow, KpiRowSkeleton } from "@/components/patterns/charts/kpi-card";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { SectionHeading } from "@/components/patterns/typography";
import { StatusBadge } from "@/components/patterns/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AiAssistantPanel } from "@/features/ai/components/ai-assistant-panel";
import { ActivityItem } from "@/features/activity/components/activity-item";
import { useMyActivity } from "@/features/activity/hooks/use-my-activity";
import { useApprovalInbox } from "@/features/approvals/hooks/use-approval-inbox";
import { StatusBreakdownChart } from "@/features/analytics/components/status-breakdown-chart";
import { RequestTrendPanel } from "@/features/analytics/components/request-trend-panel";
import { useDashboardSummary } from "@/features/dashboard/hooks/use-dashboard-summary";
import { ProfileCard } from "@/features/profile/components/profile-card";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import type { Request } from "@/types/request";
import { ROUTES } from "@/utils/constants";

function RecentRequestsList({ requests }: { requests: Request[] }) {
  if (requests.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        title="No requests yet"
        description="Create your first request to get started."
      />
    );
  }
  return (
    <ul className="divide-y">
      {requests.map((request) => (
        <li key={request.id}>
          <Link
            href={ROUTES.request(request.id)}
            className="-mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-2.5 text-sm transition-colors hover:bg-accent"
          >
            <span className="min-w-0 flex-1 truncate font-medium">{request.title}</span>
            <StatusBadge status={request.deleted_at ? "withdrawn" : request.status} />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function ApprovalsWidget({ className }: { className?: string }) {
  const { data, isLoading, isError, refetch } = useApprovalInbox({ page: 1, page_size: 5 });

  return (
    <Card className={className}>
      <CardHeader className="flex-row items-center justify-between">
        <SectionHeading>Needs your review</SectionHeading>
        <Button size="sm" variant="ghost" render={<Link href={ROUTES.approvals} />}>
          View all
          <ArrowRight className="size-4" />
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : isError || !data ? (
          <ErrorState message="Couldn't load approvals." onRetry={() => refetch()} />
        ) : data.data.length === 0 ? (
          <EmptyState icon={CheckSquare} title="Inbox zero" description="Nothing waiting on your review." />
        ) : (
          <ul className="divide-y">
            {data.data.map((item) => (
              <li key={item.stage_id}>
                <Link
                  href={ROUTES.approval(item.stage_id)}
                  className="-mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-2.5 text-sm transition-colors hover:bg-accent"
                >
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-medium">{item.request_title}</span>
                    <span className="text-muted-foreground"> · {item.stage_name}</span>
                  </span>
                  <Clock className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ActivityTimeline({ className }: { className?: string }) {
  const { data, isLoading, isError, refetch } = useMyActivity({ page: 1, page_size: 6 });

  return (
    <Card className={className}>
      <CardHeader className="flex-row items-center justify-between">
        <SectionHeading>Recent activity</SectionHeading>
        <Button size="sm" variant="ghost" render={<Link href={ROUTES.activity} />}>
          View all
          <ArrowRight className="size-4" />
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : isError || !data ? (
          <ErrorState message="Couldn't load recent activity." onRetry={() => refetch()} />
        ) : data.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recent activity.</p>
        ) : (
          <div className="space-y-1">
            {data.data.map((entry) => (
              <ActivityItem key={entry.id} entry={entry} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { data: profile } = useCurrentUser();
  const { data: summary, isLoading, isError, refetch } = useDashboardSummary();
  const canApprove = profile?.role !== "employee";

  return (
    <div className="space-y-4">
      {/* The heading and KPI row get their own slightly wider gap
       * (space-y-6, 24px) than the rest of the page's rhythm (space-y-4,
       * 16px below) — PageTitle's large display type sitting right on top
       * of a dense metric row at the same tight spacing as everything else
       * read as unbalanced. */}
      <div className="space-y-6">
        <PageHeader
          title={profile ? `Welcome back, ${profile.full_name.split(" ")[0]}` : "Dashboard"}
          description="Your open requests, pending approvals, and recent activity at a glance."
        />

        {isLoading ? (
          <KpiRowSkeleton count={canApprove ? 7 : 3} />
        ) : isError || !summary ? (
          <ErrorState message="Couldn't load your dashboard." onRetry={() => refetch()} />
        ) : (
          <KpiRow
            items={[
              { label: "Open requests", value: String(summary.open_requests_count), icon: FileText },
              ...(canApprove
                ? [
                    {
                      label: "Pending approvals",
                      value: String(summary.pending_approvals_count),
                      icon: CheckSquare,
                    },
                  ]
                : []),
              {
                label: "Unread notifications",
                value: String(summary.unread_notifications_count),
                icon: Inbox,
              },
              ...(summary.status_breakdown
                ? [{ label: "Total requests", value: String(summary.status_breakdown.total), icon: FileText }]
                : []),
              ...(summary.approval_throughput
                ? [
                    {
                      label: "Completed",
                      value: String(summary.approval_throughput.completed_count),
                      icon: CheckSquare,
                    },
                    {
                      label: "Rejected",
                      value: String(summary.approval_throughput.rejected_count),
                      icon: Clock,
                    },
                  ]
                : []),
              ...(summary.approval_throughput?.completion_rate != null
                ? [
                    {
                      label: "Org. completion rate",
                      value: `${Math.round(summary.approval_throughput.completion_rate * 100)}%`,
                      icon: BarChart3,
                    },
                  ]
                : []),
            ]}
          />
        )}
      </div>

      <div className="grid items-stretch gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-8">
          <CardHeader>
            <SectionHeading>Recent requests</SectionHeading>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : isError || !summary ? (
              <ErrorState message="Couldn't load recent requests." onRetry={() => refetch()} />
            ) : (
              <RecentRequestsList requests={summary.recent_requests} />
            )}
          </CardContent>
        </Card>

        <div className="space-y-4 xl:col-span-4">
          <Card>
            <CardHeader>
              <SectionHeading>Quick actions</SectionHeading>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <Button variant="outline" className="justify-start" render={<Link href={ROUTES.newRequest} />}>
                <Plus className="size-5" /> New request
              </Button>
              {canApprove && (
                <Button variant="outline" className="justify-start" render={<Link href={ROUTES.approvals} />}>
                  <CheckSquare className="size-5" /> Approvals
                </Button>
              )}
              {canApprove && (
                <Button variant="outline" className="justify-start" render={<Link href={ROUTES.analytics} />}>
                  <BarChart3 className="size-5" /> Analytics
                </Button>
              )}
            </CardContent>
          </Card>

          <ProfileCard />
        </div>
      </div>

      {canApprove ? (
        <>
          <div className="grid items-stretch gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-8">
              <CardHeader>
                <SectionHeading>Request trend</SectionHeading>
              </CardHeader>
              <CardContent>
                <RequestTrendPanel filters={{}} />
              </CardContent>
            </Card>
            <ApprovalsWidget className="xl:col-span-4" />
          </div>

          <AiAssistantPanel />

          <div className="grid items-stretch gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-4">
              <CardHeader>
                <SectionHeading>Workflow health</SectionHeading>
              </CardHeader>
              {/* flex-1 lets this card's content grow to match the row's
                  stretched height (set by the taller "Recent activity"
                  sibling) instead of sizing to the chart's own fixed
                  default height and leaving the rest of the card empty. */}
              <CardContent className="flex flex-1 flex-col">
                {isLoading ? (
                  <Skeleton className="h-40 w-full" />
                ) : isError || !summary ? (
                  <ErrorState message="Couldn't load the status breakdown." onRetry={() => refetch()} />
                ) : !summary.status_breakdown ? (
                  <p className="text-sm text-muted-foreground">Status breakdown unavailable.</p>
                ) : (
                  <div className="min-h-56 flex-1">
                    <StatusBreakdownChart breakdown={summary.status_breakdown} height="100%" />
                  </div>
                )}
              </CardContent>
            </Card>
            <ActivityTimeline className="xl:col-span-8" />
          </div>
        </>
      ) : (
        <ActivityTimeline />
      )}
    </div>
  );
}
