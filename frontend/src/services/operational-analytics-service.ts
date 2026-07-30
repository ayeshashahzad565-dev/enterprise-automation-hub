import { apiClient } from "@/lib/api/client";
import type {
  ApprovalDelayReport,
  BottleneckReport,
  DepartmentAnalytics,
  ExecutiveKPIs,
  OperationalAnalyticsFilters,
  SLAMetrics,
  TrendReport,
  WorkloadReport,
} from "@/types/operational-analytics";
import type { TimeGranularity } from "@/types/analytics";

function buildQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const operationalAnalyticsService = {
  getSlaMetrics: (filters: OperationalAnalyticsFilters & { sla_hours?: number } = {}) =>
    apiClient.get<SLAMetrics>(`/analytics/operational/sla${buildQuery(filters)}`),
  getApprovalDelays: (filters: OperationalAnalyticsFilters & { limit?: number } = {}) =>
    apiClient.get<ApprovalDelayReport>(`/analytics/operational/approval-delays${buildQuery(filters)}`),
  getBottlenecks: (filters: OperationalAnalyticsFilters & { limit?: number } = {}) =>
    apiClient.get<BottleneckReport>(`/analytics/operational/bottlenecks${buildQuery(filters)}`),
  getWorkloadReport: (filters: Pick<OperationalAnalyticsFilters, "department"> = {}) =>
    apiClient.get<WorkloadReport>(`/analytics/operational/workload${buildQuery(filters)}`),
  getTrends: (granularity: TimeGranularity, filters: OperationalAnalyticsFilters = {}) =>
    apiClient.get<TrendReport>(`/analytics/operational/trends${buildQuery({ granularity, ...filters })}`),
  getExecutiveKpis: (filters: OperationalAnalyticsFilters = {}) =>
    apiClient.get<ExecutiveKPIs>(`/analytics/operational/executive${buildQuery(filters)}`),
  getDepartmentAnalytics: (
    department: string,
    filters: Pick<OperationalAnalyticsFilters, "created_after" | "created_before"> = {},
  ) =>
    apiClient.get<DepartmentAnalytics>(
      `/analytics/operational/departments/${department}${buildQuery(filters)}`,
    ),
};
