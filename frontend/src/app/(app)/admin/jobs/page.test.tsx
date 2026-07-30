import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminJobsPage from "@/app/(app)/admin/jobs/page";
import { ApiError } from "@/lib/api/errors";
import { renderWithQueryClient } from "@/test/test-utils";
import type { Job, QueueStats, ScheduledJob } from "@/types/jobs";

vi.mock("@/services/admin-service", () => ({
  adminService: {
    listJobs: vi.fn(),
    listDeadLetterJobs: vi.fn(),
    getJob: vi.fn(),
    getQueueStats: vi.fn(),
    listScheduledJobs: vi.fn(),
    retryJob: vi.fn(),
    enableScheduledJob: vi.fn(),
    disableScheduledJob: vi.fn(),
    triggerScheduledJob: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { adminService } from "@/services/admin-service";
import { toast } from "sonner";

const listJobsMock = vi.mocked(adminService.listJobs);
const listDeadLetterJobsMock = vi.mocked(adminService.listDeadLetterJobs);
const getQueueStatsMock = vi.mocked(adminService.getQueueStats);
const listScheduledJobsMock = vi.mocked(adminService.listScheduledJobs);
const retryJobMock = vi.mocked(adminService.retryJob);
const disableScheduledJobMock = vi.mocked(adminService.disableScheduledJob);
const triggerScheduledJobMock = vi.mocked(adminService.triggerScheduledJob);

function buildJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    task_type: "send_email",
    queue_name: "default",
    priority: "normal",
    status: "queued",
    payload: { to: "user@example.com" },
    attempts: 0,
    max_attempts: 5,
    last_error: null,
    error_history: [],
    scheduled_for: null,
    started_at: null,
    finished_at: null,
    locked_by: null,
    request_id: null,
    actor_id: null,
    created_at: "2026-07-20T00:00:00Z",
    ...overrides,
  };
}

function buildScheduledJob(overrides: Partial<ScheduledJob> = {}): ScheduledJob {
  return {
    name: "escalation_check",
    interval_seconds: 3600,
    enabled: true,
    run_count: 42,
    success_count: 40,
    failure_count: 2,
    skipped_overlap_count: 0,
    currently_running: false,
    last_started_at: "2026-07-24T10:00:00Z",
    last_finished_at: "2026-07-24T10:00:01Z",
    last_duration_seconds: 1.23,
    last_error: null,
    next_run_time: "2026-07-24T11:00:00Z",
    ...overrides,
  };
}

function buildQueueStats(overrides: Partial<QueueStats> = {}): QueueStats {
  return {
    queue_depth: [{ queue_name: "default", priority: "high", depth: 0 }],
    delayed_count: { default: 0 },
    dead_letter_count: { default: 2 },
    ...overrides,
  };
}

function pageOf(items: Job[], overrides: Partial<{ page: number; page_size: number; total_records: number; total_pages: number }> = {}) {
  return {
    data: items,
    pagination: {
      page: 1,
      page_size: 20,
      total_records: items.length,
      total_pages: 1,
      ...overrides,
    },
  };
}

function stubDefaults() {
  listJobsMock.mockResolvedValue(pageOf([]));
  listDeadLetterJobsMock.mockResolvedValue(pageOf([]));
  getQueueStatsMock.mockResolvedValue(buildQueueStats());
  listScheduledJobsMock.mockResolvedValue([buildScheduledJob()]);
}

describe("AdminJobsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubDefaults();
  });

  it("shows loading skeletons, then renders queue stats, scheduled jobs, and job history once data arrives", async () => {
    listJobsMock.mockResolvedValueOnce(pageOf([buildJob({ task_type: "send_invitation_email" })]));

    renderWithQueryClient(<AdminJobsPage />);

    expect(screen.getAllByText("Jobs")[0]).toBeInTheDocument();
    await screen.findByText("send_invitation_email");
    expect(await screen.findByText("escalation_check")).toBeInTheDocument();
    expect(screen.getByText("every 1h")).toBeInTheDocument();
  });

  it("shows an empty state with no jobs in the history table", async () => {
    renderWithQueryClient(<AdminJobsPage />);

    expect(await screen.findByText("No jobs yet")).toBeInTheDocument();
  });

  it("renders the inactive state when queue_depth/delayed_count are null", async () => {
    getQueueStatsMock.mockResolvedValueOnce(
      buildQueueStats({ queue_depth: null, delayed_count: null, dead_letter_count: { default: 0 } }),
    );

    renderWithQueryClient(<AdminJobsPage />);

    const inactiveMessages = await screen.findAllByText(
      "Inactive — Redis isn't configured on this backend instance.",
    );
    expect(inactiveMessages).toHaveLength(2);
  });

  it("re-queries job history with the selected status filter", async () => {
    listJobsMock.mockResolvedValue(pageOf([buildJob()]));
    const user = userEvent.setup();
    renderWithQueryClient(<AdminJobsPage />);
    await screen.findByText("send_email");

    await user.click(screen.getAllByRole("combobox")[0]);
    await user.click(await screen.findByRole("option", { name: "Succeeded" }));

    await waitFor(() =>
      expect(listJobsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "succeeded", page: 1 }),
      ),
    );
  });

  it("enables/disables a scheduled job from its switch and shows a confirmation toast", async () => {
    disableScheduledJobMock.mockResolvedValueOnce(null);
    const user = userEvent.setup();
    renderWithQueryClient(<AdminJobsPage />);
    await screen.findByText("escalation_check");

    await user.click(screen.getByRole("switch"));

    await waitFor(() => expect(disableScheduledJobMock).toHaveBeenCalledWith("escalation_check"));
    expect(toast.success).toHaveBeenCalledWith("escalation_check disabled.");
  });

  it("triggers a scheduled job now and shows a confirmation toast", async () => {
    triggerScheduledJobMock.mockResolvedValueOnce({ triggered: true });
    const user = userEvent.setup();
    renderWithQueryClient(<AdminJobsPage />);
    await screen.findByText("escalation_check");

    await user.click(screen.getByRole("button", { name: /trigger now/i }));

    await waitFor(() => expect(triggerScheduledJobMock).toHaveBeenCalledWith("escalation_check"));
    expect(toast.success).toHaveBeenCalledWith("escalation_check triggered — it'll run in the background.");
  });

  it("disables the trigger-now button while a scheduled job is currently running", async () => {
    listScheduledJobsMock.mockResolvedValueOnce([
      buildScheduledJob({ currently_running: true }),
    ]);
    renderWithQueryClient(<AdminJobsPage />);
    await screen.findByText("escalation_check");

    expect(screen.getByRole("button", { name: /trigger now/i })).toBeDisabled();
  });

  it("asks for confirmation before retrying a dead-lettered job, and does nothing on cancel", async () => {
    listDeadLetterJobsMock.mockResolvedValue(
      pageOf([buildJob({ id: "job-dl", task_type: "escalate_stage", status: "dead_lettered" })]),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<AdminJobsPage />);
    await screen.findByText("escalate_stage");

    await user.click(screen.getByRole("button", { name: /^retry$/i }));
    expect(await screen.findByText("Retry this job?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => expect(screen.queryByText("Retry this job?")).not.toBeInTheDocument());
    expect(retryJobMock).not.toHaveBeenCalled();
  });

  it("retries a dead-lettered job after confirmation and refreshes the lists", async () => {
    listDeadLetterJobsMock.mockResolvedValue(
      pageOf([buildJob({ id: "job-dl", task_type: "escalate_stage", status: "dead_lettered" })]),
    );
    retryJobMock.mockResolvedValueOnce(buildJob({ id: "job-dl", status: "queued", attempts: 0 }));
    const user = userEvent.setup();
    renderWithQueryClient(<AdminJobsPage />);
    await screen.findByText("escalate_stage");
    const callsBeforeRetry = listDeadLetterJobsMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: /^retry$/i }));
    await screen.findByText("Retry this job?");
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^retry$/i }));

    await waitFor(() => expect(retryJobMock).toHaveBeenCalledWith("job-dl"));
    expect(toast.success).toHaveBeenCalledWith("escalate_stage requeued.");
    await waitFor(() =>
      expect(listDeadLetterJobsMock.mock.calls.length).toBeGreaterThan(callsBeforeRetry),
    );
  });

  it("shows an error toast when retry fails, without leaking backend detail", async () => {
    listDeadLetterJobsMock.mockResolvedValue(
      pageOf([buildJob({ id: "job-dl", task_type: "escalate_stage", status: "dead_lettered" })]),
    );
    retryJobMock.mockRejectedValueOnce(
      new ApiError({ code: "VALIDATION_ERROR", message: "Job is not dead-lettered.", status: 422 }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<AdminJobsPage />);
    await screen.findByText("escalate_stage");

    await user.click(screen.getByRole("button", { name: /^retry$/i }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^retry$/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Job is not dead-lettered."));
  });

  it("opens the job detail panel with payload JSON when a history row is clicked", async () => {
    listJobsMock.mockResolvedValueOnce(
      pageOf([
        buildJob({
          task_type: "send_reminder",
          payload: { request_id: "req-123" },
          error_history: [{ attempt: 1, error: "SMTP timeout", at: "2026-07-24T10:00:00Z" }],
        }),
      ]),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<AdminJobsPage />);
    await screen.findByText("send_reminder");

    const row = screen.getByText("send_reminder").closest("tr");
    if (!row) throw new Error("Row not found");
    await user.click(row);

    expect(await screen.findByText(/"request_id"/)).toBeInTheDocument();
    expect(screen.getByText("SMTP timeout")).toBeInTheDocument();
  });
});
