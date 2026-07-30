import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PlatformHealthPage from "@/app/(app)/platform/health/page";
import { renderWithQueryClient } from "@/test/test-utils";
import type { PlatformHealth } from "@/types/platform";

vi.mock("@/services/platform-service", () => ({
  platformService: {
    getHealth: vi.fn(),
  },
}));

import { platformService } from "@/services/platform-service";

const getHealthMock = vi.mocked(platformService.getHealth);

function buildHealth(overrides: Partial<PlatformHealth> = {}): PlatformHealth {
  return {
    status: "ok",
    database: "ok",
    scheduler_active: true,
    ...overrides,
  };
}

describe("PlatformHealthPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders OK status cards when every dependency is healthy", async () => {
    getHealthMock.mockResolvedValueOnce(buildHealth());

    renderWithQueryClient(<PlatformHealthPage />);

    expect(await screen.findByText("Database")).toBeInTheDocument();
    const okBadges = await screen.findAllByText("OK");
    expect(okBadges.length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Not configured")).toHaveLength(2);
  });

  it("shows Redis/job-queue details and the dead-letter backlog when Redis is configured", async () => {
    getHealthMock.mockResolvedValueOnce(
      buildHealth({
        redis: "ok",
        job_queue: "ok",
        dead_letter_by_queue: { default: 3, escalation: 0 },
      }),
    );

    renderWithQueryClient(<PlatformHealthPage />);

    await screen.findByText("Database");
    expect(screen.getByText("default")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows an unreachable database as a distinct badge", async () => {
    getHealthMock.mockResolvedValueOnce(buildHealth({ status: "degraded", database: "unreachable" }));

    renderWithQueryClient(<PlatformHealthPage />);

    expect(await screen.findByText("Unreachable")).toBeInTheDocument();
  });

  it("shows an error state and can retry", async () => {
    getHealthMock.mockRejectedValueOnce(new Error("network error"));
    getHealthMock.mockResolvedValueOnce(buildHealth());

    renderWithQueryClient(<PlatformHealthPage />);

    expect(await screen.findByText("Couldn't load platform health.")).toBeInTheDocument();
  });
});
