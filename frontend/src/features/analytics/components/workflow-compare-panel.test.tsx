import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowComparePanel } from "@/features/analytics/components/workflow-compare-panel";
import { renderWithQueryClient } from "@/test/test-utils";
import type { WorkflowMetrics } from "@/types/analytics";

vi.mock("@/services/analytics-service", () => ({
  analyticsService: {
    getWorkflowMetrics: vi.fn(),
  },
}));

import { analyticsService } from "@/services/analytics-service";

const getWorkflowMetricsMock = vi.mocked(analyticsService.getWorkflowMetrics);

function buildMetrics(overrides: Partial<WorkflowMetrics> = {}): WorkflowMetrics {
  return {
    request_type: "expense_reimbursement",
    status_breakdown: { counts: { pending: 2 }, total: 5 },
    approval_metrics: {
      throughput: {
        average_decision_seconds: 3600,
        completed_count: 3,
        rejected_count: 1,
        completion_rate: 0.6,
      },
      average_stage_duration_seconds: null,
      approval_latency_seconds: null,
      escalation_count: null,
      reminder_count: null,
    },
    throughput_per_day: null,
    ...overrides,
  };
}

async function addRequestType(user: ReturnType<typeof userEvent.setup>, name: string) {
  const input = screen.getByPlaceholderText("Add a workflow type...");
  await user.type(input, name);
  await user.click(screen.getByRole("button", { name: "Add" }));
}

describe("WorkflowComparePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the add-a-workflow-type prompt when nothing has been added yet", () => {
    renderWithQueryClient(<WorkflowComparePanel filters={{}} />);

    expect(
      screen.getByText(/Add a workflow type .* to compare its request volume\./),
    ).toBeInTheDocument();
  });

  it("surfaces a query failure with a working retry instead of silently showing the empty-state copy", async () => {
    const user = userEvent.setup();
    getWorkflowMetricsMock.mockRejectedValue(new Error("boom"));

    renderWithQueryClient(<WorkflowComparePanel filters={{}} />);
    await addRequestType(user, "expense_reimbursement");

    expect(
      await screen.findByText("Couldn't load one or more workflow types."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Add a workflow type .* to compare its request volume\./),
    ).not.toBeInTheDocument();

    getWorkflowMetricsMock.mockResolvedValue(buildMetrics());
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(getWorkflowMetricsMock).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.queryByText("Couldn't load one or more workflow types."),
      ).not.toBeInTheDocument(),
    );
  });
});
