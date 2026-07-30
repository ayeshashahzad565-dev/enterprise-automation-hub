/**
 * Frontend-owned types for the `/api/v1/analytics/operational/*`
 * resources (Milestone 12) — defined independently of the backend's
 * Pydantic schemas, matching the convention `types/analytics.ts`
 * already follows.
 */

import type { TimeSeries } from "@/types/analytics";
import type { UserMetrics } from "@/types/analytics";
import type { UserRole } from "@/types/workflow";

export interface PendingApprovalAge {
  stage_id: string;
  request_id: string;
  request_title: string;
  request_type: string;
  department: string | null;
  stage_name: string;
  stage_order: number;
  assigned_to: string | null;
  assigned_role: UserRole | null;
  created_at: string;
  age_hours: number;
  sla_hours: number | null;
  is_overdue: boolean;
}

export interface SLAMetrics {
  sla_hours_override: number | null;
  pending_stage_count: number;
  overdue_stage_count: number;
  overdue_request_count: number;
  average_current_stage_age_hours: number | null;
  decided_stage_count: number;
  sla_breaches_decided: number;
  sla_compliance_percentage: number | null;
  average_total_workflow_duration_seconds: number | null;
  average_approval_duration_seconds: number | null;
}

export interface DurationBucket {
  key: string;
  average_seconds: number | null;
  count: number;
}

export interface ApprovalDelayReport {
  longest_pending: PendingApprovalAge[];
  oldest_pending_requests: PendingApprovalAge[];
  average_approval_seconds: number | null;
  median_approval_seconds: number | null;
  duration_by_stage: DurationBucket[];
  duration_by_department: DurationBucket[];
  duration_by_workflow: DurationBucket[];
}

export interface CountBucket {
  key: string;
  count: number;
}

export interface RejectionBucket {
  key: string;
  decided_count: number;
  rejected_count: number;
  rejection_rate: number | null;
}

export interface BottleneckReport {
  slowest_stages: DurationBucket[];
  slowest_workflows: DurationBucket[];
  departments_causing_delay: DurationBucket[];
  approver_queue_depth: UserMetrics[];
  frequently_overdue_stages: CountBucket[];
  rejection_hotspots: RejectionBucket[];
}

export interface WorkloadReport {
  approvals_per_approver: UserMetrics[];
  requests_per_department: Record<string, number>;
  requests_per_workflow: Record<string, number>;
  completed_today: number;
  completed_this_week: number;
  completed_this_month: number;
  active_workload: number;
  completed_workload: number;
  pending_workload: number;
}

export interface TrendReport {
  request_volume: TimeSeries;
  completion_trend: TimeSeries;
  approval_trend: TimeSeries;
  rejection_trend: TimeSeries;
  average_completion_time_trend: TimeSeries;
}

export interface ExecutiveKPIs {
  average_approval_seconds: number | null;
  average_workflow_completion_seconds: number | null;
  sla_compliance_percentage: number | null;
  active_requests: number;
  completed_requests: number;
  pending_approvals: number;
  overdue_approvals: number;
  rejection_rate: number | null;
  throughput_per_day: number | null;
  workflow_efficiency_score: number | null;
}

export interface DepartmentAnalytics {
  department: string;
  throughput_per_day: number | null;
  sla_compliance_percentage: number | null;
  average_approval_seconds: number | null;
  active_workload: number;
  backlog_count: number;
}

export interface OperationalAnalyticsFilters {
  department?: string;
  request_type?: string;
  created_after?: string;
  created_before?: string;
}
