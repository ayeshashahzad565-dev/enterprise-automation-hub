import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateInvitationDialog } from "@/features/admin/components/create-invitation-dialog";
import { ApiError } from "@/lib/api/errors";
import { renderWithQueryClient } from "@/test/test-utils";
import type { Invitation } from "@/types/admin";

vi.mock("@/services/admin-service", () => ({
  adminService: {
    createInvitation: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { adminService } from "@/services/admin-service";
import { toast } from "sonner";

const createInvitationMock = vi.mocked(adminService.createInvitation);

describe("CreateInvitationDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("rejects submission with empty required fields", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithQueryClient(<CreateInvitationDialog open onOpenChange={onOpenChange} />);

    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    expect(await screen.findByText("Full name is required.")).toBeInTheDocument();
    expect(screen.getByText("Email is required.")).toBeInTheDocument();
    expect(createInvitationMock).not.toHaveBeenCalled();
  });

  it("rejects a malformed email address", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CreateInvitationDialog open onOpenChange={vi.fn()} />);

    await user.type(screen.getByLabelText("Full name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(createInvitationMock).not.toHaveBeenCalled();
  });

  it("submits the expected payload and shows a success toast on success", async () => {
    createInvitationMock.mockResolvedValueOnce({
      id: "inv-1",
      email: "ada@example.com",
      full_name: "Ada Lovelace",
      role: "employee",
      department: "engineering",
      effective_status: "pending",
      invited_by: "admin-1",
      expires_at: new Date().toISOString(),
      accepted_at: null,
      revoked_at: null,
      accepted_profile_id: null,
      resend_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithQueryClient(<CreateInvitationDialog open onOpenChange={onOpenChange} />);

    await user.type(screen.getByLabelText("Full name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Department"), "engineering");
    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    await waitFor(() =>
      expect(createInvitationMock).toHaveBeenCalledWith({
        full_name: "Ada Lovelace",
        email: "ada@example.com",
        role: "employee",
        department: "engineering",
      }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toast.success).toHaveBeenCalledWith("Invitation sent to ada@example.com.");
  });

  it("shows the server's error message in a toast and keeps the dialog open on failure", async () => {
    createInvitationMock.mockRejectedValueOnce(
      new ApiError({
        code: "VALIDATION_ERROR",
        message: "A conflicting invitation already exists.",
        status: 422,
      }),
    );
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithQueryClient(<CreateInvitationDialog open onOpenChange={onOpenChange} />);

    await user.type(screen.getByLabelText("Full name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("A conflicting invitation already exists."),
    );
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("disables the submit button while the request is pending", async () => {
    let resolveCreate!: (value: Invitation) => void;
    createInvitationMock.mockReturnValueOnce(
      new Promise<Invitation>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<CreateInvitationDialog open onOpenChange={vi.fn()} />);

    await user.type(screen.getByLabelText("Full name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: /send invitation/i }));

    expect(await screen.findByRole("button", { name: /sending/i })).toBeDisabled();

    resolveCreate({
      id: "inv-1",
      email: "ada@example.com",
      full_name: "Ada Lovelace",
      role: "employee",
      department: null,
      effective_status: "pending",
      invited_by: "admin-1",
      expires_at: new Date().toISOString(),
      accepted_at: null,
      revoked_at: null,
      accepted_profile_id: null,
      resend_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  });

  it("cancels without submitting", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithQueryClient(<CreateInvitationDialog open onOpenChange={onOpenChange} />);

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(createInvitationMock).not.toHaveBeenCalled();
  });
});
