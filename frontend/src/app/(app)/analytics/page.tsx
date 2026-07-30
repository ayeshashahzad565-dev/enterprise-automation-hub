"use client";

import { Inbox, Sparkles } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { ChartSkeleton } from "@/components/patterns/charts/chart-skeleton";
import { KpiRowSkeleton } from "@/components/patterns/charts/kpi-card";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Metric, SectionHeading } from "@/components/patterns/typography";
import { Button } from "@/components/ui/button";
import { SavedViewsMenu } from "@/components/patterns/saved-views-menu";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AnalyticsFilterBar,
  EMPTY_ANALYTICS_FILTERS,
  type AnalyticsFilterState,
} from "@/features/analytics/components/analytics-filter-bar";
import { AgingRequestsTable } from "@/features/analytics/components/aging-requests-table";
import { ApprovalDelayTable } from "@/features/analytics/components/approval-delay-table";
import { DepartmentComparePanel } from "@/features/analytics/components/department-compare-panel";
import { DepartmentOperationalPanel } from "@/features/analytics/components/department-operational-panel";
import { DurationBucketTable } from "@/features/analytics/components/duration-bucket-table";
import { ExecutiveKpiRow } from "@/features/analytics/components/executive-kpi-row";
import { ExecutiveNarrativePanel } from "@/features/analytics/components/executive-narrative-panel";
import { ExportButton } from "@/features/analytics/components/export-button";
import { DashboardKpiRow } from "@/features/analytics/components/kpi-row";
import { OperationalTrendPanel } from "@/features/analytics/components/operational-trend-panel";
import { RejectionHotspotsTable } from "@/features/analytics/components/rejection-hotspots-table";
import { RequestTrendPanel } from "@/features/analytics/components/request-trend-panel";
import { SlaIndicatorRow } from "@/features/analytics/components/sla-indicator-row";
import { StatusBreakdownChart } from "@/features/analytics/components/status-breakdown-chart";
import { UserMetricsLookupPanel } from "@/features/analytics/components/user-metrics-lookup-panel";
import { WorkflowComparePanel } from "@/features/analytics/components/workflow-compare-panel";
import { WorkloadTable } from "@/features/analytics/components/workload-table";
import { AiInsightCard } from "@/features/ai/components/ai-insight-card";
import { useAiExecutiveSummary } from "@/features/ai/hooks/use-ai-executive-summary";
import { useBottleneckExplanation } from "@/features/ai/hooks/use-bottleneck-explanation";
import { useOperationalInsights } from "@/features/ai/hooks/use-operational-insights";
import { usePolicyRecommendations } from "@/features/ai/hooks/use-policy-recommendations";
import { useAgingRequests } from "@/features/analytics/hooks/use-aging-requests";
import { useApprovalDelays } from "@/features/analytics/hooks/use-approval-delays";
import { useBottlenecks } from "@/features/analytics/hooks/use-bottlenecks";
import { useDashboardMetrics } from "@/features/analytics/hooks/use-dashboard-metrics";
import { useExecutiveKpis } from "@/features/analytics/hooks/use-executive-kpis";
import { useExecutiveSummary } from "@/features/analytics/hooks/use-executive-summary";
import { useOperationalWorkload } from "@/features/analytics/hooks/use-operational-workload";
import { useSavedViews, type AnalyticsSavedView } from "@/features/analytics/hooks/use-saved-views";
import { useSlaMetrics } from "@/features/analytics/hooks/use-sla-metrics";
import { useWorkloadSummary } from "@/features/analytics/hooks/use-workload-summary";
import { ActivityItem } from "@/features/activity/components/activity-item";
import { useOrganizationActivity } from "@/features/activity/hooks/use-organization-activity";
import { useApprovalInbox } from "@/features/approvals/hooks/use-approval-inbox";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import type { AnalyticsFilters } from "@/types/analytics";
import { ROUTES } from "@/utils/constants";

function toApiFilters(state: AnalyticsFilterState): AnalyticsFilters {
  return {
    department: state.department || undefined,
    request_type: state.requestType || undefined,
    created_after: state.createdAfter || undefined,
    created_before: state.createdBefore || undefined,
  };
}

export default function AnalyticsPage() {
  const { data: profile } = useCurrentUser();
  const isAdmin = profile?.role === "admin";

  const [activeTab, setActiveTab] = useState("executive");
  const [sharedFilters, setSharedFilters] = useState<AnalyticsFilterState>(EMPTY_ANALYTICS_FILTERS);
  const apiFilters = useMemo(() => toApiFilters(sharedFilters), [sharedFilters]);

  return (
    <div className="space-y-3">
      <PageHeader
        title="Analytics"
        description="Operational visibility across requests, approvals, and workflows."
      />

      {/* gap-3 (12px) overrides Tabs' own default gap-2 (8px) — kept
       * deliberately tight so the tab strip, filter row, and KPI cards
       * read as one cohesive control section rather than three
       * separately-spaced blocks. */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="gap-3">
        <TabsList>
          <TabsTrigger value="executive">Executive</TabsTrigger>
          <TabsTrigger value="operational">Operational</TabsTrigger>
          <TabsTrigger value="intelligence">Intelligence</TabsTrigger>
          <TabsTrigger value="explorer">Explorer</TabsTrigger>
        </TabsList>

        {/* Executive and Operational share one filter bar/state; Explorer
            keeps its own independent filters (and its own Saved Views),
            so it isn't shown here — previously this exact filter bar was
            rendered three times, once per tab. The Executive tab's export
            action sits in this same row (rather than its own row below,
            which left a stray band of empty space above the KPI cards). */}
        {activeTab !== "explorer" && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <AnalyticsFilterBar value={sharedFilters} onChange={setSharedFilters} />
            {activeTab === "executive" && (
              <ExportButton endpoint="dashboard" filters={apiFilters} filename="dashboard-metrics.csv" />
            )}
          </div>
        )}

        <TabsContent value="executive" className="space-y-4">
          <ExecutiveTab filters={apiFilters} />
        </TabsContent>

        <TabsContent value="operational" className="space-y-4">
          <OperationalTab isAdmin={isAdmin} department={apiFilters.department} />
        </TabsContent>

        <TabsContent value="intelligence" className="space-y-4">
          <IntelligenceTab filters={apiFilters} />
        </TabsContent>

        <TabsContent value="explorer" className="space-y-4">
          <ExplorerTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ExecutiveTab({ filters }: { filters: AnalyticsFilters }) {
  const dashboardQuery = useDashboardMetrics(filters);
  const summaryQuery = useExecutiveSummary({
    created_after: filters.created_after,
    created_before: filters.created_before,
  });
  const aiSummaryQuery = useAiExecutiveSummary();

  if (dashboardQuery.isLoading) {
    return (
      <div className="space-y-4">
        <KpiRowSkeleton />
        <div className="grid items-stretch gap-4 lg:grid-cols-2">
          <ChartSkeleton />
          <ChartSkeleton />
        </div>
      </div>
    );
  }
  if (dashboardQuery.isError || !dashboardQuery.data) {
    return (
      <ErrorState message="Couldn't load dashboard metrics." onRetry={() => dashboardQuery.refetch()} />
    );
  }

  const metrics = dashboardQuery.data;

  return (
    <div className="space-y-4">
      <DashboardKpiRow metrics={metrics} />
      {/* Request trend is the primary chart (8/12 width) — Status
          breakdown is secondary, at 4/12 width, rather than every panel
          on this tab carrying identical visual weight. */}
      <div className="grid items-stretch gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-8">
          <CardHeader>
            <SectionHeading>Request trend</SectionHeading>
          </CardHeader>
          <CardContent>
            <RequestTrendPanel filters={filters} />
          </CardContent>
        </Card>
        <Card className="xl:col-span-4">
          <CardHeader>
            <SectionHeading>Status breakdown</SectionHeading>
          </CardHeader>
          <CardContent>
            <StatusBreakdownChart breakdown={metrics.status_breakdown} />
          </CardContent>
        </Card>
      </div>
      <div className="grid items-stretch gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-8">
          <CardHeader>
            <SectionHeading>Compare departments</SectionHeading>
          </CardHeader>
          <CardContent>
            <DepartmentComparePanel
              filters={{ created_after: filters.created_after, created_before: filters.created_before }}
            />
          </CardContent>
        </Card>
        <ExecutiveNarrativePanel
          narrative={summaryQuery.data?.narrative}
          isLoading={summaryQuery.isLoading}
          isError={summaryQuery.isError}
          onRetry={() => summaryQuery.refetch()}
          className="xl:col-span-4"
        />
      </div>
      <AiInsightCard
        title="AI executive summary"
        icon={Sparkles}
        data={aiSummaryQuery.data}
        isLoading={aiSummaryQuery.isLoading}
        isError={aiSummaryQuery.isError}
        onRetry={() => aiSummaryQuery.refetch()}
      />
    </div>
  );
}

function OperationalTab({ isAdmin, department }: { isAdmin: boolean; department?: string }) {
  const inboxQuery = useApprovalInbox({ page: 1, page_size: 1 });
  const workloadQuery = useWorkloadSummary(department);
  const agingQuery = useAgingRequests({ older_than_hours: 24, page_size: 20 });
  const activityQuery = useOrganizationActivity({ page_size: 20 });

  return (
    <div className="space-y-4">
      <div className="grid items-stretch gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <SectionHeading>My pending approvals</SectionHeading>
          </CardHeader>
          <CardContent className={inboxQuery.isLoading || inboxQuery.isError || !inboxQuery.data ? undefined : "flex items-center justify-between"}>
            {inboxQuery.isLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : inboxQuery.isError || !inboxQuery.data ? (
              <ErrorState
                message="Couldn't load pending approvals."
                onRetry={() => inboxQuery.refetch()}
              />
            ) : (
              <>
                <Metric>{inboxQuery.data.pagination.total_records}</Metric>
                <Button size="sm" variant="outline" render={<Link href={ROUTES.approvals} />}>
                  View queue
                </Button>
              </>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <SectionHeading>Workload distribution</SectionHeading>
          </CardHeader>
          <CardContent>
            {workloadQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : workloadQuery.isError || !workloadQuery.data ? (
              <ErrorState message="Couldn't load workload." onRetry={() => workloadQuery.refetch()} />
            ) : (
              <WorkloadTable users={workloadQuery.data} />
            )}
          </CardContent>
        </Card>
      </div>

      {isAdmin ? (
        <>
          <Card>
            <CardHeader>
              <SectionHeading>Aging requests / bottlenecks</SectionHeading>
            </CardHeader>
            <CardContent>
              {agingQuery.isLoading ? (
                <Skeleton className="h-32 w-full" />
              ) : agingQuery.isError || !agingQuery.data ? (
                <ErrorState message="Couldn't load aging requests." onRetry={() => agingQuery.refetch()} />
              ) : (
                <AgingRequestsTable items={agingQuery.data.data} />
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <SectionHeading>Recent activity</SectionHeading>
            </CardHeader>
            <CardContent>
              {activityQuery.isLoading ? (
                <Skeleton className="h-32 w-full" />
              ) : activityQuery.isError || !activityQuery.data ? (
                <ErrorState
                  message="Couldn't load recent activity."
                  onRetry={() => activityQuery.refetch()}
                />
              ) : activityQuery.data.data.length === 0 ? (
                <p className="text-sm text-muted-foreground">No recent activity.</p>
              ) : (
                <div className="space-y-1">
                  {activityQuery.data.data.map((entry) => (
                    <ActivityItem key={entry.id} entry={entry} />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      ) : (
        <EmptyState
          icon={Inbox}
          title="Admin-only"
          description="Aging requests and recent activity are visible to administrators only."
        />
      )}
    </div>
  );
}

function IntelligenceTab({ filters }: { filters: AnalyticsFilters }) {
  const slaQuery = useSlaMetrics(filters);
  const kpiQuery = useExecutiveKpis(filters);
  const delaysQuery = useApprovalDelays({ ...filters, limit: 10 });
  const bottlenecksQuery = useBottlenecks({ ...filters, limit: 10 });
  const workloadQuery = useOperationalWorkload(filters.department);
  const bottleneckExplanationQuery = useBottleneckExplanation();
  const policyRecommendationsQuery = usePolicyRecommendations();
  const operationalInsightsQuery = useOperationalInsights();

  if (kpiQuery.isLoading || slaQuery.isLoading) {
    return (
      <div className="space-y-4">
        <KpiRowSkeleton />
        <KpiRowSkeleton />
      </div>
    );
  }
  if (kpiQuery.isError || !kpiQuery.data || slaQuery.isError || !slaQuery.data) {
    return (
      <ErrorState
        message="Couldn't load operational intelligence."
        onRetry={() => {
          kpiQuery.refetch();
          slaQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-4">
      <ExecutiveKpiRow kpis={kpiQuery.data} />
      <SlaIndicatorRow metrics={slaQuery.data} />

      <div className="grid items-stretch gap-4 xl:grid-cols-12">
        <AiInsightCard
          title="Bottleneck explanation"
          icon={Sparkles}
          data={bottleneckExplanationQuery.data}
          isLoading={bottleneckExplanationQuery.isLoading}
          isError={bottleneckExplanationQuery.isError}
          onRetry={() => bottleneckExplanationQuery.refetch()}
          className="xl:col-span-4"
        />
        <AiInsightCard
          title="Policy recommendations"
          icon={Sparkles}
          data={policyRecommendationsQuery.data}
          isLoading={policyRecommendationsQuery.isLoading}
          isError={policyRecommendationsQuery.isError}
          onRetry={() => policyRecommendationsQuery.refetch()}
          className="xl:col-span-4"
        />
        <AiInsightCard
          title="Operational insights"
          icon={Sparkles}
          data={operationalInsightsQuery.data}
          isLoading={operationalInsightsQuery.isLoading}
          isError={operationalInsightsQuery.isError}
          onRetry={() => operationalInsightsQuery.refetch()}
          className="xl:col-span-4"
        />
      </div>

      <Card>
        <CardHeader>
          <SectionHeading>Execution trends</SectionHeading>
        </CardHeader>
        <CardContent>
          <OperationalTrendPanel filters={filters} />
        </CardContent>
      </Card>

      <div className="grid items-stretch gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-6">
          <CardHeader>
            <SectionHeading>Top delayed requests</SectionHeading>
          </CardHeader>
          <CardContent>
            {delaysQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : delaysQuery.isError || !delaysQuery.data ? (
              <ErrorState
                message="Couldn't load approval delays."
                onRetry={() => delaysQuery.refetch()}
              />
            ) : (
              <ApprovalDelayTable items={delaysQuery.data.longest_pending} />
            )}
          </CardContent>
        </Card>
        <Card className="xl:col-span-6">
          <CardHeader>
            <SectionHeading>Top overloaded approvers</SectionHeading>
          </CardHeader>
          <CardContent>
            {workloadQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : workloadQuery.isError || !workloadQuery.data ? (
              <ErrorState message="Couldn't load workload." onRetry={() => workloadQuery.refetch()} />
            ) : (
              <WorkloadTable
                users={[...workloadQuery.data.approvals_per_approver]
                  .sort((a, b) => b.pending_assigned_count - a.pending_assigned_count)
                  .slice(0, 10)}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid items-stretch gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-4">
          <CardHeader>
            <SectionHeading>Slowest stages</SectionHeading>
          </CardHeader>
          <CardContent>
            {bottlenecksQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : bottlenecksQuery.isError || !bottlenecksQuery.data ? (
              <ErrorState
                message="Couldn't load bottlenecks."
                onRetry={() => bottlenecksQuery.refetch()}
              />
            ) : (
              <DurationBucketTable
                buckets={bottlenecksQuery.data.slowest_stages}
                keyLabel="Stage"
                emptyMessage="No decided stages in scope."
              />
            )}
          </CardContent>
        </Card>
        <Card className="xl:col-span-4">
          <CardHeader>
            <SectionHeading>Departments causing delay</SectionHeading>
          </CardHeader>
          <CardContent>
            {bottlenecksQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : bottlenecksQuery.isError || !bottlenecksQuery.data ? (
              <ErrorState
                message="Couldn't load bottlenecks."
                onRetry={() => bottlenecksQuery.refetch()}
              />
            ) : (
              <DurationBucketTable
                buckets={bottlenecksQuery.data.departments_causing_delay}
                keyLabel="Department"
                emptyMessage="No decided stages in scope."
              />
            )}
          </CardContent>
        </Card>
        <Card className="xl:col-span-4">
          <CardHeader>
            <SectionHeading>Rejection hotspots</SectionHeading>
          </CardHeader>
          <CardContent>
            {bottlenecksQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : bottlenecksQuery.isError || !bottlenecksQuery.data ? (
              <ErrorState
                message="Couldn't load bottlenecks."
                onRetry={() => bottlenecksQuery.refetch()}
              />
            ) : (
              <RejectionHotspotsTable buckets={bottlenecksQuery.data.rejection_hotspots} />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <SectionHeading>Department comparison</SectionHeading>
        </CardHeader>
        <CardContent>
          <DepartmentOperationalPanel
            filters={{ created_after: filters.created_after, created_before: filters.created_before }}
          />
        </CardContent>
      </Card>
    </div>
  );
}

function ExplorerTab() {
  const [filters, setFilters] = useState<AnalyticsFilterState>(EMPTY_ANALYTICS_FILTERS);
  const { views, saveView, removeView } = useSavedViews();
  const apiFilters = useMemo(() => toApiFilters(filters), [filters]);

  const dashboardQuery = useDashboardMetrics(apiFilters);

  function applyView(view: AnalyticsSavedView) {
    setFilters({
      department: view.department ?? "",
      requestType: view.requestType ?? "",
      createdAfter: view.createdAfter ?? "",
      createdBefore: view.createdBefore ?? "",
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <AnalyticsFilterBar value={filters} onChange={setFilters} />
        <div className="flex items-center gap-2">
          <SavedViewsMenu
            views={views}
            onApply={applyView}
            onSave={(name) =>
              saveView({
                name,
                department: filters.department || undefined,
                requestType: filters.requestType || undefined,
                createdAfter: filters.createdAfter || undefined,
                createdBefore: filters.createdBefore || undefined,
              })
            }
            onRemove={removeView}
          />
          <ExportButton endpoint="dashboard" filters={apiFilters} filename="explorer-dashboard.csv" />
        </div>
      </div>

      {dashboardQuery.isLoading ? (
        <KpiRowSkeleton />
      ) : dashboardQuery.isError || !dashboardQuery.data ? (
        <ErrorState
          message="Couldn't load metrics for this filter."
          onRetry={() => dashboardQuery.refetch()}
        />
      ) : (
        <>
          <DashboardKpiRow metrics={dashboardQuery.data} />
          <div className="grid items-stretch gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <SectionHeading>Status breakdown</SectionHeading>
              </CardHeader>
              <CardContent>
                <StatusBreakdownChart breakdown={dashboardQuery.data.status_breakdown} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <SectionHeading>Trend</SectionHeading>
              </CardHeader>
              <CardContent>
                <RequestTrendPanel filters={apiFilters} />
              </CardContent>
            </Card>
          </div>
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <SectionHeading>Compare workflow types</SectionHeading>
              </CardHeader>
              <CardContent>
                <WorkflowComparePanel filters={apiFilters} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <SectionHeading>Look up a user</SectionHeading>
              </CardHeader>
              <CardContent>
                <UserMetricsLookupPanel />
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
