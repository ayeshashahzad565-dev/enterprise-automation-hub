import { apiClient } from "@/lib/api/client";
import type {
  AgingRequestItem,
  AnalyticsFilters,
  AnalyticsSummary,
  ApprovalMetrics,
  DashboardMetrics,
  DepartmentMetrics,
  TimeGranularity,
  TimeSeries,
  UserMetrics,
  WorkflowMetrics,
} from "@/types/analytics";

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

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export const analyticsService = {
  getDashboardMetrics: (filters: AnalyticsFilters = {}) =>
    apiClient.get<DashboardMetrics>(`/analytics/dashboard${buildQuery(filters)}`),
  getApprovalMetrics: (filters: AnalyticsFilters = {}) =>
    apiClient.get<ApprovalMetrics>(`/analytics/approvals${buildQuery(filters)}`),
  getWorkflowMetrics: (requestType: string, filters: Omit<AnalyticsFilters, "request_type"> = {}) =>
    apiClient.get<WorkflowMetrics>(`/analytics/workflow/${requestType}${buildQuery(filters)}`),
  getDepartmentMetrics: (
    department: string,
    filters: Omit<AnalyticsFilters, "department" | "request_type"> = {},
  ) => apiClient.get<DepartmentMetrics>(`/analytics/departments/${department}${buildQuery(filters)}`),
  getUserMetrics: (userId: string) => apiClient.get<UserMetrics>(`/analytics/users/${userId}`),
  getWorkloadSummary: (department?: string) =>
    apiClient.get<UserMetrics[]>(`/analytics/workload${buildQuery({ department })}`),
  getTrend: (
    granularity: TimeGranularity,
    filters: Omit<AnalyticsFilters, "request_type"> & { request_type?: string } = {},
  ) => apiClient.get<TimeSeries>(`/analytics/trend${buildQuery({ granularity, ...filters })}`),
  getExecutiveSummary: (filters: Pick<AnalyticsFilters, "created_after" | "created_before"> = {}) =>
    apiClient.get<AnalyticsSummary>(`/analytics/summary/executive${buildQuery(filters)}`),
  getOperationalSummary: (filters: Pick<AnalyticsFilters, "created_after" | "created_before"> = {}) =>
    apiClient.get<AnalyticsSummary>(`/analytics/summary/operational${buildQuery(filters)}`),
  getAgingRequests: (params: { older_than_hours?: number; page?: number; page_size?: number } = {}) =>
    apiClient.getList<AgingRequestItem>(`/analytics/aging-requests${buildQuery(params)}`),
  exportCsv: async (endpoint: string, filters: object, filename: string) => {
    const path = `/analytics/${endpoint}${buildQuery({ ...filters, format: "csv" })}`;
    const blob = await apiClient.getBlob(path);
    downloadBlob(blob, filename);
  },
};
