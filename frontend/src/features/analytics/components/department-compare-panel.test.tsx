import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DepartmentComparePanel } from "@/features/analytics/components/department-compare-panel";
import { renderWithQueryClient } from "@/test/test-utils";
import type { DepartmentMetrics } from "@/types/analytics";

vi.mock("@/services/analytics-service", () => ({
  analyticsService: {
    getDepartmentMetrics: vi.fn(),
  },
}));

import { analyticsService } from "@/services/analytics-service";

const getDepartmentMetricsMock = vi.mocked(analyticsService.getDepartmentMetrics);

function buildMetrics(overrides: Partial<DepartmentMetrics> = {}): DepartmentMetrics {
  return {
    department: "Engineering",
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
    workload: 4,
    ...overrides,
  };
}

async function addDepartment(user: ReturnType<typeof userEvent.setup>, name: string) {
  const input = screen.getByPlaceholderText("Add a department...");
  await user.type(input, name);
  await user.click(screen.getByRole("button", { name: "Add" }));
}

describe("DepartmentComparePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the add-a-department prompt when nothing has been added yet", () => {
    renderWithQueryClient(<DepartmentComparePanel filters={{}} />);

    expect(
      screen.getByText("Add a department to compare its request volume."),
    ).toBeInTheDocument();
  });

  it("surfaces a query failure with a working retry instead of silently showing the empty-state copy", async () => {
    const user = userEvent.setup();
    getDepartmentMetricsMock.mockRejectedValue(new Error("boom"));

    renderWithQueryClient(<DepartmentComparePanel filters={{}} />);
    await addDepartment(user, "Sales");

    expect(await screen.findByText("Couldn't load one or more departments.")).toBeInTheDocument();
    // The old bug rendered this exact empty-state copy on failure — it
    // must never appear once a department has actually been added.
    expect(
      screen.queryByText("Add a department to compare its request volume."),
    ).not.toBeInTheDocument();

    getDepartmentMetricsMock.mockResolvedValue(buildMetrics({ department: "Sales" }));
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(getDepartmentMetricsMock).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByText("Couldn't load one or more departments.")).not.toBeInTheDocument(),
    );
  });

  it("shows an error when only some of several departments fail to load", async () => {
    getDepartmentMetricsMock.mockImplementation((department: string) =>
      department === "Sales"
        ? Promise.reject(new Error("boom"))
        : Promise.resolve(buildMetrics({ department })),
    );
    const user = userEvent.setup();

    renderWithQueryClient(<DepartmentComparePanel filters={{}} />);
    await addDepartment(user, "Engineering");
    await addDepartment(user, "Sales");

    expect(await screen.findByText("Couldn't load one or more departments.")).toBeInTheDocument();
  });
});
