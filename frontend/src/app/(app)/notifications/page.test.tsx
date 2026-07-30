import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationsPage from "@/app/(app)/notifications/page";
import { renderWithQueryClient } from "@/test/test-utils";
import type { Notification } from "@/types/notification";

vi.mock("@/services/notification-service", () => ({
  notificationService: {
    list: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
    archive: vi.fn(),
    unarchive: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { notificationService } from "@/services/notification-service";

const listMock = vi.mocked(notificationService.list);

function buildNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n-1",
    recipient_id: "user-1",
    request_id: null,
    notification_type: "system",
    message: "Budget approved",
    is_read: false,
    read_at: null,
    email_sent: true,
    email_sent_at: "2026-07-20T00:00:00Z",
    archived_at: null,
    is_archived: false,
    created_at: "2026-07-20T00:00:00Z",
    ...overrides,
  };
}

function pageOf(items: Notification[]) {
  return {
    data: items,
    pagination: { page: 1, page_size: 20, total_records: items.length, total_pages: 1 },
  };
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMock.mockResolvedValue(pageOf([buildNotification()]));
  });

  it("sends the debounced search term to the backend rather than filtering client-side", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<NotificationsPage />);
    await screen.findByText("Budget approved");
    listMock.mockClear();

    await user.type(screen.getByPlaceholderText("Search notifications..."), "budget");

    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ search: "budget" })),
      { timeout: 2000 },
    );
  });

  it("links to the notification preferences page", async () => {
    renderWithQueryClient(<NotificationsPage />);
    await screen.findByText("Budget approved");

    const link = screen.getByRole("button", { name: /preferences/i });
    expect(link).toHaveAttribute("href", "/notifications/preferences");
  });
});
