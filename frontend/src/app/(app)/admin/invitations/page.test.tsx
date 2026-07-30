import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminInvitationsPage from "@/app/(app)/admin/invitations/page";
import { ApiError } from "@/lib/api/errors";
import { renderWithQueryClient } from "@/test/test-utils";
import type { Invitation } from "@/types/admin";

vi.mock("@/services/admin-service", () => ({
  adminService: {
    listInvitations: vi.fn(),
    createInvitation: vi.fn(),
    resendInvitation: vi.fn(),
    revokeInvitation: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { adminService } from "@/services/admin-service";
import { toast } from "sonner";

const listInvitationsMock = vi.mocked(adminService.listInvitations);
const resendInvitationMock = vi.mocked(adminService.resendInvitation);
const revokeInvitationMock = vi.mocked(adminService.revokeInvitation);

function buildInvitation(overrides: Partial<Invitation> = {}): Invitation {
  return {
    id: "inv-1",
    email: "ivy@example.com",
    full_name: "Ivy Invitee",
    role: "employee",
    department: "sales",
    effective_status: "pending",
    invited_by: "admin-1",
    expires_at: "2026-08-01T00:00:00Z",
    accepted_at: null,
    revoked_at: null,
    accepted_profile_id: null,
    resend_count: 0,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function pageOf(items: Invitation[], overrides: Partial<{ page: number; page_size: number; total_records: number; total_pages: number }> = {}) {
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

async function openRowMenu(rowName: RegExp) {
  const user = userEvent.setup();
  const row = screen.getByText(rowName).closest("tr");
  if (!row) throw new Error("Row not found");
  await user.click(within(row).getByRole("button", { name: /open quick actions/i }));
  return user;
}

describe("AdminInvitationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton, then renders the table once data arrives", async () => {
    listInvitationsMock.mockResolvedValueOnce(pageOf([buildInvitation()]));
    renderWithQueryClient(<AdminInvitationsPage />);

    expect(screen.getAllByText("Invitations")[0]).toBeInTheDocument();
    await screen.findByText("Ivy Invitee");
    expect(screen.getByText("ivy@example.com")).toBeInTheDocument();
    expect(screen.getByText("sales")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("shows an empty state with no invitations", async () => {
    listInvitationsMock.mockResolvedValueOnce(pageOf([]));
    renderWithQueryClient(<AdminInvitationsPage />);

    expect(await screen.findByText("No invitations yet")).toBeInTheDocument();
  });

  it("shows a 'no matching invitations' empty state while a search is active", async () => {
    listInvitationsMock.mockResolvedValueOnce(pageOf([buildInvitation()]));
    const user = userEvent.setup();
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");

    listInvitationsMock.mockResolvedValue(pageOf([]));
    await user.type(screen.getByPlaceholderText("Search by name or email..."), "nobody");

    expect(await screen.findByText("No matching invitations")).toBeInTheDocument();
  });

  it("shows an error state and can retry", async () => {
    listInvitationsMock.mockRejectedValueOnce(new Error("boom"));
    renderWithQueryClient(<AdminInvitationsPage />);

    expect(await screen.findByText("Couldn't load invitations.")).toBeInTheDocument();

    listInvitationsMock.mockResolvedValueOnce(pageOf([buildInvitation()]));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await screen.findByText("Ivy Invitee");
  });

  it("re-queries with the typed search term", async () => {
    listInvitationsMock.mockResolvedValue(pageOf([buildInvitation()]));
    const user = userEvent.setup();
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");

    await user.type(screen.getByPlaceholderText("Search by name or email..."), "ivy");

    await waitFor(() =>
      expect(listInvitationsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: "ivy", page: 1 }),
      ),
    );
  });

  it("re-queries with the selected status filter", async () => {
    listInvitationsMock.mockResolvedValue(pageOf([buildInvitation()]));
    const user = userEvent.setup();
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");

    // The status filter is the first combobox in DOM order — the
    // pagination control's "rows per page" Select is the second.
    await user.click(screen.getAllByRole("combobox")[0]);
    await user.click(await screen.findByRole("option", { name: "Revoked" }));

    await waitFor(() =>
      expect(listInvitationsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "revoked", page: 1 }),
      ),
    );
  });

  it("re-queries the next page", async () => {
    listInvitationsMock.mockResolvedValue(
      pageOf([buildInvitation()], { page: 1, total_records: 40, total_pages: 2 }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");

    await user.click(screen.getByRole("button", { name: /next page/i }));

    await waitFor(() =>
      expect(listInvitationsMock).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })),
    );
  });

  it("resends an invitation and refreshes the list", async () => {
    listInvitationsMock.mockResolvedValue(pageOf([buildInvitation()]));
    resendInvitationMock.mockResolvedValueOnce(buildInvitation({ resend_count: 1 }));
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");
    const callsBeforeResend = listInvitationsMock.mock.calls.length;

    const user = await openRowMenu(/Ivy Invitee/);
    await user.click(await screen.findByRole("menuitem", { name: /^resend$/i }));

    await waitFor(() => expect(resendInvitationMock).toHaveBeenCalledWith("inv-1"));
    expect(toast.success).toHaveBeenCalledWith("Invitation resent to ivy@example.com.");
    await waitFor(() =>
      expect(listInvitationsMock.mock.calls.length).toBeGreaterThan(callsBeforeResend),
    );
  });

  it("shows an error toast when resend fails, without leaking backend detail", async () => {
    listInvitationsMock.mockResolvedValue(pageOf([buildInvitation()]));
    resendInvitationMock.mockRejectedValueOnce(new Error("network exploded"));
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");

    const user = await openRowMenu(/Ivy Invitee/);
    await user.click(await screen.findByRole("menuitem", { name: /^resend$/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Couldn't resend this invitation."),
    );
  });

  it("asks for confirmation before revoking, and does nothing on cancel", async () => {
    listInvitationsMock.mockResolvedValue(pageOf([buildInvitation()]));
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");

    const user = await openRowMenu(/Ivy Invitee/);
    await user.click(await screen.findByRole("menuitem", { name: /revoke/i }));

    expect(await screen.findByText("Revoke this invitation?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(screen.queryByText("Revoke this invitation?")).not.toBeInTheDocument(),
    );
    expect(revokeInvitationMock).not.toHaveBeenCalled();
  });

  it("revokes an invitation after confirmation and refreshes the list", async () => {
    listInvitationsMock.mockResolvedValue(pageOf([buildInvitation()]));
    revokeInvitationMock.mockResolvedValueOnce(buildInvitation({ effective_status: "revoked" }));
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");
    const callsBeforeRevoke = listInvitationsMock.mock.calls.length;

    const user = await openRowMenu(/Ivy Invitee/);
    await user.click(await screen.findByRole("menuitem", { name: /revoke/i }));
    await screen.findByText("Revoke this invitation?");
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^revoke$/i }));

    await waitFor(() => expect(revokeInvitationMock).toHaveBeenCalledWith("inv-1"));
    expect(toast.success).toHaveBeenCalledWith("Invitation revoked for ivy@example.com.");
    await waitFor(() =>
      expect(listInvitationsMock.mock.calls.length).toBeGreaterThan(callsBeforeRevoke),
    );
  });

  it("shows an error toast when revoke fails", async () => {
    listInvitationsMock.mockResolvedValue(pageOf([buildInvitation()]));
    revokeInvitationMock.mockRejectedValueOnce(
      new ApiError({ code: "VALIDATION_ERROR", message: "Already accepted.", status: 422 }),
    );
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");

    const user = await openRowMenu(/Ivy Invitee/);
    await user.click(await screen.findByRole("menuitem", { name: /revoke/i }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^revoke$/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Already accepted."));
  });

  it("hides row actions for a terminal-state invitation", async () => {
    listInvitationsMock.mockResolvedValueOnce(
      pageOf([buildInvitation({ effective_status: "accepted" })]),
    );
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("Ivy Invitee");

    expect(screen.queryByRole("button", { name: /open quick actions/i })).not.toBeInTheDocument();
  });

  it("opens the create-invitation dialog from the primary action", async () => {
    listInvitationsMock.mockResolvedValue(pageOf([]));
    const user = userEvent.setup();
    renderWithQueryClient(<AdminInvitationsPage />);
    await screen.findByText("No invitations yet");

    await user.click(screen.getAllByRole("button", { name: /new invitation/i })[0]);

    expect(await screen.findByText("Invite a new user")).toBeInTheDocument();
  });
});
