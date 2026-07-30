/**
 * Frontend-owned types for the `/api/v1/analytics*` and `/api/v1/audit-logs`
 * resources — defined independently of the backend's Pydantic schemas,
 * matching the convention every other `types/*.ts` file in this project
 * follows.
 */

import type { RequestStatus } from "@/types/request";
import type { StageStatus, UserRole } from "@/types/workflow";

export type TimeGranularity = "day" | "week" | "month";

export interface StatusBreakdown {
  counts: Partial<Record<RequestStatus, number>>;
  total: number;
}

export interface ApprovalThroughput {
  average_decision_seconds: number | null;
  completed_count: number;
  rejected_count: number;
  completion_rate: number | null;
}

export interface ApprovalMetrics {
  throughput: ApprovalThroughput;
  average_stage_duration_seconds: number | null;
  approval_latency_seconds: number | null;
  escalation_count: number | null;
  reminder_count: number | null;
}

export interface DashboardMetrics {
  status_breakdown: StatusBreakdown;
  total_requests: number;
  active_requests: number;
  completed_requests: number;
  rejected_requests: number;
  approval_metrics: ApprovalMetrics;
}

export interface WorkflowMetrics {
  request_type: string;
  status_breakdown: StatusBreakdown;
  approval_metrics: ApprovalMetrics;
  throughput_per_day: number | null;
}

export interface DepartmentMetrics {
  department: string;
  status_breakdown: StatusBreakdown;
  approval_metrics: ApprovalMetrics;
  workload: number;
}

export interface UserMetrics {
  user_id: string;
  full_name: string;
  role: UserRole;
  decisions_approved: number;
  decisions_rejected: number;
  pending_assigned_count: number;
  average_decision_seconds: number | null;
  decisions_made: number;
}

export interface TrendPoint {
  label: string;
  period_start: string;
  period_end: string;
  value: number;
}

export interface TimeSeries {
  granularity: TimeGranularity;
  points: TrendPoint[];
  total: number;
}

export interface AnalyticsSummary {
  title: string;
  generated_at: string;
  dashboard: DashboardMetrics | null;
  workflow_metrics: WorkflowMetrics[];
  department_metrics: DepartmentMetrics[];
  user_metrics: UserMetrics[];
  trend: TimeSeries | null;
  narrative: string;
}

export interface AgingRequestItem {
  stage_id: string;
  stage_version: number;
  stage_order: number;
  stage_name: string;
  stage_status: StageStatus;
  assigned_role: UserRole | null;
  stage_created_at: string;
  age_hours: number;
  request_id: string;
  request_title: string;
  request_type: string;
  department: string | null;
  requester_id: string;
  request_status: RequestStatus;
}

export interface AnalyticsFilters {
  department?: string;
  request_type?: string;
  created_after?: string;
  created_before?: string;
}
