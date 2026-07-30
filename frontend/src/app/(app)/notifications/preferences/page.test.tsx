import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationPreferencesPage from "@/app/(app)/notifications/preferences/page";
import { renderWithQueryClient } from "@/test/test-utils";
import type { NotificationPreference } from "@/types/notification";

vi.mock("@/services/notification-service", () => ({
  notificationService: {
    getPreferences: vi.fn(),
    updatePreference: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { notificationService } from "@/services/notification-service";
import { toast } from "sonner";

const getPreferencesMock = vi.mocked(notificationService.getPreferences);
const updatePreferenceMock = vi.mocked(notificationService.updatePreference);

function buildPreferences(
  overrides: Partial<Record<NotificationPreference["notification_type"], Partial<NotificationPreference>>> = {},
): NotificationPreference[] {
  const types: NotificationPreference["notification_type"][] = [
    "assignment",
    "reminder",
    "escalation",
    "decision",
    "completion",
    "system",
  ];
  return types.map((notification_type) => ({
    notification_type,
    in_app_enabled: true,
    email_enabled: true,
    updated_at: null,
    ...overrides[notification_type],
  }));
}

describe("NotificationPreferencesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders every notification type once preferences load", async () => {
    getPreferencesMock.mockResolvedValueOnce(buildPreferences());

    renderWithQueryClient(<NotificationPreferencesPage />);

    expect(await screen.findByText("Assignment")).toBeInTheDocument();
    expect(screen.getByText("Reminder")).toBeInTheDocument();
    expect(screen.getByText("Escalation")).toBeInTheDocument();
    expect(screen.getByText("Decision")).toBeInTheDocument();
    expect(screen.getByText("Completion")).toBeInTheDocument();
    expect(screen.getByText("System")).toBeInTheDocument();
    expect(screen.getAllByRole("switch")).toHaveLength(12);
  });

  it("shows an error state when loading fails, with a working retry", async () => {
    getPreferencesMock.mockRejectedValueOnce(new Error("network error"));
    getPreferencesMock.mockResolvedValueOnce(buildPreferences());
    const user = userEvent.setup();

    renderWithQueryClient(<NotificationPreferencesPage />);

    await screen.findByText("Couldn't load your notification preferences.");
    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Assignment")).toBeInTheDocument();
  });

  it("toggles a preference and shows an error toast on failure", async () => {
    getPreferencesMock.mockResolvedValueOnce(buildPreferences());
    updatePreferenceMock.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();

    renderWithQueryClient(<NotificationPreferencesPage />);
    await screen.findByText("Assignment");

    await user.click(
      screen.getByRole("switch", { name: "Disable in-app Assignment notifications" }),
    );

    await waitFor(() =>
      expect(updatePreferenceMock).toHaveBeenCalledWith("assignment", { in_app_enabled: false }),
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Couldn't update your notification preference."),
    );
  });

  it("disables the email switch once in-app delivery is off", async () => {
    getPreferencesMock.mockResolvedValueOnce(
      buildPreferences({ reminder: { in_app_enabled: false } }),
    );

    renderWithQueryClient(<NotificationPreferencesPage />);
    await screen.findByText("Reminder");

    expect(
      screen.getByRole("switch", { name: "Disable email Reminder notifications" }),
    ).toHaveAttribute("aria-disabled", "true");
  });
});
