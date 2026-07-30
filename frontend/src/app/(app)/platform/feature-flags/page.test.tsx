import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PlatformFeatureFlagsPage from "@/app/(app)/platform/feature-flags/page";
import { renderWithQueryClient } from "@/test/test-utils";
import type { FeatureFlag } from "@/types/platform";

vi.mock("@/services/platform-service", () => ({
  platformService: {
    listFeatureFlags: vi.fn(),
    createFeatureFlag: vi.fn(),
    updateFeatureFlag: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { platformService } from "@/services/platform-service";
import { toast } from "sonner";

const listFlagsMock = vi.mocked(platformService.listFeatureFlags);
const createFlagMock = vi.mocked(platformService.createFeatureFlag);
const updateFlagMock = vi.mocked(platformService.updateFeatureFlag);

function buildFlag(overrides: Partial<FeatureFlag> = {}): FeatureFlag {
  return {
    key: "new_dashboard",
    description: "New dashboard layout",
    enabled: false,
    updated_at: "2026-07-20T00:00:00Z",
    ...overrides,
  };
}

describe("PlatformFeatureFlagsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an empty state with no flags", async () => {
    listFlagsMock.mockResolvedValueOnce([]);

    renderWithQueryClient(<PlatformFeatureFlagsPage />);

    expect(await screen.findByText("No feature flags yet")).toBeInTheDocument();
  });

  it("renders every flag once loaded", async () => {
    listFlagsMock.mockResolvedValueOnce([buildFlag({ key: "new_dashboard" }), buildFlag({ key: "beta_export" })]);

    renderWithQueryClient(<PlatformFeatureFlagsPage />);

    expect(await screen.findByText("new_dashboard")).toBeInTheDocument();
    expect(screen.getByText("beta_export")).toBeInTheDocument();
  });

  it("toggles a flag and shows an error toast on failure", async () => {
    listFlagsMock.mockResolvedValueOnce([buildFlag()]);
    updateFlagMock.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();

    renderWithQueryClient(<PlatformFeatureFlagsPage />);
    await screen.findByText("new_dashboard");

    await user.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(updateFlagMock).toHaveBeenCalledWith("new_dashboard", { enabled: true }),
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Couldn't update this feature flag."),
    );
  });

  it("creates a new flag from the dialog", async () => {
    listFlagsMock.mockResolvedValueOnce([]);
    createFlagMock.mockResolvedValueOnce(buildFlag({ key: "beta_export" }));
    const user = userEvent.setup();

    renderWithQueryClient(<PlatformFeatureFlagsPage />);
    await screen.findByText("No feature flags yet");

    await user.click(screen.getByRole("button", { name: /new flag/i }));
    await user.type(screen.getByLabelText("Key"), "beta_export");
    await user.type(screen.getByLabelText("Description"), "Beta export feature");
    await user.click(screen.getByRole("button", { name: /create flag/i }));

    await waitFor(() =>
      expect(createFlagMock).toHaveBeenCalledWith({
        key: "beta_export",
        description: "Beta export feature",
        enabled: false,
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("beta_export created.");
  });
});
