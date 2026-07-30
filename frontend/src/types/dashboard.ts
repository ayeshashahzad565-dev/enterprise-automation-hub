/**
 * Frontend-owned type for `/api/v1/dashboard-summary` — defined
 * independently of the backend's Pydantic schema, matching the
 * convention every other `types/*.ts` file in this project follows.
 * `status_breakdown`/`approval_throughput` are `null` for an `employee`
 * caller (the backend's own least-privilege policy — see
 * `DashboardService.get_dashboard_summary`'s docstring), never omitted.
 */

import type { ApprovalThroughput, StatusBreakdown } from "@/types/analytics";
import type { Request } from "@/types/request";

export interface DashboardSummary {
  open_requests_count: number;
  pending_approvals_count: number;
  unread_notifications_count: number;
  recent_requests: Request[];
  status_breakdown: StatusBreakdown | null;
  approval_throughput: ApprovalThroughput | null;
}
