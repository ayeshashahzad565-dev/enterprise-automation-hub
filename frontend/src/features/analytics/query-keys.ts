/** Centralized TanStack Query key factory for the Analytics feature. */
export const analyticsKeys = {
  all: ["analytics"] as const,
  dashboard: (filters: object) => [...analyticsKeys.all, "dashboard", filters] as const,
  approvals: (filters: object) => [...analyticsKeys.all, "approvals", filters] as const,
  workflow: (requestType: string, filters: object) =>
    [...analyticsKeys.all, "workflow", requestType, filters] as const,
  department: (department: string, filters: object) =>
    [...analyticsKeys.all, "department", department, filters] as const,
  user: (userId: string) => [...analyticsKeys.all, "user", userId] as const,
  workload: (department?: string) => [...analyticsKeys.all, "workload", department ?? null] as const,
  trend: (granularity: string, filters: object) =>
    [...analyticsKeys.all, "trend", granularity, filters] as const,
  executiveSummary: (filters: object) => [...analyticsKeys.all, "summary", "executive", filters] as const,
  operationalSummary: (filters: object) => [...analyticsKeys.all, "summary", "operational", filters] as const,
  agingRequests: (params: object) => [...analyticsKeys.all, "aging-requests", params] as const,
};

/** Centralized TanStack Query key factory for the Operational Analytics feature (Milestone 12). */
export const operationalAnalyticsKeys = {
  all: ["operational-analytics"] as const,
  sla: (filters: object) => [...operationalAnalyticsKeys.all, "sla", filters] as const,
  approvalDelays: (filters: object) =>
    [...operationalAnalyticsKeys.all, "approval-delays", filters] as const,
  bottlenecks: (filters: object) => [...operationalAnalyticsKeys.all, "bottlenecks", filters] as const,
  workload: (filters: object) => [...operationalAnalyticsKeys.all, "workload", filters] as const,
  trends: (granularity: string, filters: object) =>
    [...operationalAnalyticsKeys.all, "trends", granularity, filters] as const,
  executive: (filters: object) => [...operationalAnalyticsKeys.all, "executive", filters] as const,
  department: (department: string, filters: object) =>
    [...operationalAnalyticsKeys.all, "department", department, filters] as const,
};
