import { apiClient } from "@/lib/api/client";
import type { DashboardSummary } from "@/types/dashboard";

export const dashboardService = {
  getSummary: () => apiClient.get<DashboardSummary>("/dashboard-summary"),
};
