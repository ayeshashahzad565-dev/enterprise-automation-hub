import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DepartmentOperationalPanel } from "@/features/analytics/components/department-operational-panel";
import { renderWithQueryClient } from "@/test/test-utils";
import type { DepartmentAnalytics } from "@/types/operational-analytics";

vi.mock("@/services/operational-analytics-service", () => ({
  operationalAnalyticsService: {
    getDepartmentAnalytics: vi.fn(),
  },
}));

import { operationalAnalyticsService } from "@/services/operational-analytics-service";

const getDepartmentAnalyticsMock = vi.mocked(operationalAnalyticsService.getDepartmentAnalytics);

function buildAnalytics(overrides: Partial<DepartmentAnalytics> = {}): DepartmentAnalytics {
  return {
    department: "Engineering",
    throughput_per_day: 2.5,
    sla_compliance_percentage: 0.9,
    average_approval_seconds: 3600,
    active_workload: 4,
    backlog_count: 1,
    ...overrides,
  };
}

async function addDepartment(user: ReturnType<typeof userEvent.setup>, name: string) {
  const input = screen.getByPlaceholderText("Add a department...");
  await user.type(input, name);
  await user.click(screen.getByRole("button", { name: "Add" }));
}

describe("DepartmentOperationalPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the no-departments-added empty state when nothing has been added yet", () => {
    renderWithQueryClient(<DepartmentOperationalPanel filters={{}} />);

    expect(screen.getByText("No departments added")).toBeInTheDocument();
  });

  it("surfaces a query failure with a working retry instead of silently showing the empty-state copy", async () => {
    const user = userEvent.setup();
    getDepartmentAnalyticsMock.mockRejectedValue(new Error("boom"));

    renderWithQueryClient(<DepartmentOperationalPanel filters={{}} />);
    await addDepartment(user, "Sales");

    expect(await screen.findByText("Couldn't load one or more departments.")).toBeInTheDocument();
    expect(screen.queryByText("No departments added")).not.toBeInTheDocument();

    getDepartmentAnalyticsMock.mockResolvedValue(buildAnalytics({ department: "Sales" }));
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(getDepartmentAnalyticsMock).toHaveBeenCalledTimes(2));
    // "Sales" also appears in the still-present filter chip above the
    // table, so assert on a value unique to the resolved table row.
    expect(await screen.findByText("90%")).toBeInTheDocument();
  });
});
