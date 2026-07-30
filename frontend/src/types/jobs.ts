/**
 * Frontend-owned types for the background Job system module
 * (`/api/v1/admin/jobs`, `/api/v1/admin/scheduled-jobs`) — defined
 * independently of the backend's Pydantic schemas, matching the
 * convention every other `types/*.ts` file in this project follows.
 */

export type JobStatus = "queued" | "running" | "retrying" | "succeeded" | "dead_lettered";

export type JobPriority = "high" | "normal" | "low";

export interface JobErrorHistoryEntry {
  attempt: number;
  error: string;
  at: string;
}

export interface Job {
  id: string;
  task_type: string;
  queue_name: string;
  priority: JobPriority;
  status: JobStatus;
  /** Arbitrary JSON payload. Sensitive fields (e.g. `token` on
   * `send_invitation_email`) are already redacted server-side — no
   * frontend redaction is applied or required. */
  payload: Record<string, unknown>;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  error_history: JobErrorHistoryEntry[];
  scheduled_for: string | null;
  started_at: string | null;
  finished_at: string | null;
  locked_by: string | null;
  request_id: string | null;
  actor_id: string | null;
  created_at: string;
}

/** Mirrors the scheduler's own health-tracking fields for a registered
 * scheduled (cron-like) job — e.g. `escalation_check`, `reminder_dispatch`,
 * `stuck_job_reaper`, `scheduler_health_check` in the reference deployment,
 * though the set of names is whatever the backend instance registers. */
export interface ScheduledJob {
  name: string;
  interval_seconds: number;
  enabled: boolean;
  run_count: number;
  success_count: number;
  failure_count: number;
  skipped_overlap_count: number;
  currently_running: boolean;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_duration_seconds: number | null;
  last_error: string | null;
  next_run_time: string | null;
}

export interface QueueDepthEntry {
  queue_name: string;
  priority: JobPriority;
  depth: number;
}

/** `queue_depth`/`delayed_count` are `null` (not empty) when Redis isn't
 * configured on the backend instance — that must be rendered as an
 * "inactive"/"n/a" state, never coerced to zero. */
export interface QueueStats {
  queue_depth: QueueDepthEntry[] | null;
  delayed_count: Record<string, number> | null;
  dead_letter_count: Record<string, number>;
}
