import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationBell } from "@/features/notifications/components/notification-bell";
import { renderWithQueryClient } from "@/test/test-utils";
import type { Notification } from "@/types/notification";

vi.mock("@/services/notification-service", () => ({
  notificationService: {
    getUnreadCount: vi.fn(),
    list: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
    archive: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { notificationService } from "@/services/notification-service";

const getUnreadCountMock = vi.mocked(notificationService.getUnreadCount);
const listMock = vi.mocked(notificationService.list);

function buildNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n-1",
    recipient_id: "user-1",
    request_id: null,
    notification_type: "system",
    message: "Hello",
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

function pageOf(items: Notification[], page: number, totalPages: number) {
  return {
    data: items,
    pagination: { page, page_size: 8, total_records: totalPages * 8, total_pages: totalPages },
  };
}

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getUnreadCountMock.mockResolvedValue({ unread_count: 2 });
  });

  it("shows the unread badge and opens the dropdown with the first page of notifications", async () => {
    listMock.mockResolvedValueOnce(pageOf([buildNotification({ message: "First item" })], 1, 1));
    const user = userEvent.setup();

    renderWithQueryClient(<NotificationBell />);
    expect(await screen.findByText("2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Notifications" }));

    expect(await screen.findByText("First item")).toBeInTheDocument();
    expect(listMock).toHaveBeenCalledWith(expect.objectContaining({ page: 1, page_size: 8 }));
  });

  it("fetches the next page when the list is scrolled near the bottom", async () => {
    listMock.mockResolvedValueOnce(pageOf([buildNotification({ id: "n-1", message: "Page one item" })], 1, 2));
    listMock.mockResolvedValueOnce(pageOf([buildNotification({ id: "n-2", message: "Page two item" })], 2, 2));
    const user = userEvent.setup();

    renderWithQueryClient(<NotificationBell />);
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    const item = await screen.findByText("Page one item");

    const scrollContainer = item.closest(".overflow-y-auto");
    if (!scrollContainer) throw new Error("Scroll container not found");
    Object.defineProperty(scrollContainer, "scrollHeight", { value: 400, configurable: true });
    Object.defineProperty(scrollContainer, "clientHeight", { value: 200, configurable: true });
    Object.defineProperty(scrollContainer, "scrollTop", { value: 380, configurable: true });
    scrollContainer.dispatchEvent(new Event("scroll", { bubbles: true }));

    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 8 }));
    expect(await screen.findByText("Page two item")).toBeInTheDocument();
  });

  it("does not fetch another page when the list is not scrolled near the bottom", async () => {
    listMock.mockResolvedValueOnce(pageOf([buildNotification({ message: "Only item" })], 1, 2));
    const user = userEvent.setup();

    renderWithQueryClient(<NotificationBell />);
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    const item = await screen.findByText("Only item");

    const scrollContainer = item.closest(".overflow-y-auto");
    if (!scrollContainer) throw new Error("Scroll container not found");
    Object.defineProperty(scrollContainer, "scrollHeight", { value: 400, configurable: true });
    Object.defineProperty(scrollContainer, "clientHeight", { value: 200, configurable: true });
    Object.defineProperty(scrollContainer, "scrollTop", { value: 0, configurable: true });
    scrollContainer.dispatchEvent(new Event("scroll", { bubbles: true }));

    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(listMock).toHaveBeenCalledTimes(1);
  });

  it("links to the notification preferences page", async () => {
    listMock.mockResolvedValueOnce(pageOf([], 1, 1));
    const user = userEvent.setup();

    renderWithQueryClient(<NotificationBell />);
    await user.click(screen.getByRole("button", { name: "Notifications" }));

    const link = await screen.findByRole("button", { name: "Notification preferences" });
    expect(link).toHaveAttribute("href", "/notifications/preferences");
  });
});
