import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AcceptInviteContent } from "@/features/invitation-acceptance/components/accept-invite-content";
import { ApiError } from "@/lib/api/errors";
import { renderWithQueryClient } from "@/test/test-utils";
import type { InvitationValidation } from "@/types/invitation";

let mockSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
}));

vi.mock("@/services/invitation-service", () => ({
  invitationService: {
    validate: vi.fn(),
    accept: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { invitationService } from "@/services/invitation-service";
import { toast } from "sonner";

const validateMock = vi.mocked(invitationService.validate);
const acceptMock = vi.mocked(invitationService.accept);

const VALID_INVITATION: InvitationValidation = {
  email: "ivy@example.com",
  full_name: "Ivy Invitee",
  role: "employee",
  department: "sales",
  expires_at: "2026-08-01T00:00:00Z",
};

function setToken(token: string | null) {
  mockSearchParams = token === null ? new URLSearchParams() : new URLSearchParams({ token });
}

describe("AcceptInviteContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setToken("good-token");
  });

  it("shows a loading skeleton while validating, then the invitation details", async () => {
    let resolveValidate!: (value: InvitationValidation) => void;
    validateMock.mockReturnValueOnce(
      new Promise<InvitationValidation>((resolve) => {
        resolveValidate = resolve;
      }),
    );
    renderWithQueryClient(<AcceptInviteContent />);

    // Loading: the form isn't present yet.
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();

    resolveValidate(VALID_INVITATION);

    expect(await screen.findByText("Ivy Invitee")).toBeInTheDocument();
    expect(screen.getByText("ivy@example.com")).toBeInTheDocument();
    expect(screen.getByText("employee")).toBeInTheDocument();
    expect(screen.getByText("sales")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("never calls the API and shows the generic invalid state when no token is present", async () => {
    setToken(null);
    renderWithQueryClient(<AcceptInviteContent />);

    expect(
      await screen.findByText(/invalid or has expired/i),
    ).toBeInTheDocument();
    expect(validateMock).not.toHaveBeenCalled();
  });

  it("shows the generic invalid-invitation message for a 404 from validate", async () => {
    validateMock.mockRejectedValueOnce(
      new ApiError({
        code: "RESOURCE_NOT_FOUND",
        message: "This invitation link is invalid or has expired.",
        status: 404,
      }),
    );
    renderWithQueryClient(<AcceptInviteContent />);

    expect(await screen.findByText(/invalid or has expired/i)).toBeInTheDocument();
    // Never a distinguishing word like "expired"/"revoked" beyond the one fixed sentence.
    expect(screen.queryByText(/revoked/i)).not.toBeInTheDocument();
  });

  it("shows a generic retry experience for a network/infrastructure failure, and can retry", async () => {
    validateMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderWithQueryClient(<AcceptInviteContent />);

    expect(
      await screen.findByText(/something went wrong on our end/i),
    ).toBeInTheDocument();

    validateMock.mockResolvedValueOnce(VALID_INVITATION);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Ivy Invitee")).toBeInTheDocument();
  });

  it("shows a generic retry experience for a 500 from validate", async () => {
    validateMock.mockRejectedValueOnce(
      new ApiError({ code: "INTERNAL_ERROR", message: "An unexpected error occurred.", status: 500 }),
    );
    renderWithQueryClient(<AcceptInviteContent />);

    expect(await screen.findByText(/something went wrong on our end/i)).toBeInTheDocument();
  });

  it("accepts the invitation and shows the success screen with a link to login, without auto-login", async () => {
    validateMock.mockResolvedValueOnce(VALID_INVITATION);
    acceptMock.mockResolvedValueOnce({ email: "ivy@example.com", full_name: "Ivy Invitee" });
    const user = userEvent.setup();
    renderWithQueryClient(<AcceptInviteContent />);
    await screen.findByLabelText("Password");

    await user.type(screen.getByLabelText("Password"), "correct-horse-1");
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-1");
    await user.click(screen.getByRole("button", { name: /set password/i }));

    await waitFor(() =>
      expect(acceptMock.mock.calls[0]?.[0]).toEqual({
        token: "good-token",
        password: "correct-horse-1",
      }),
    );
    expect(await screen.findByText(/you're all set, ivy invitee/i)).toBeInTheDocument();
    const loginLink = screen.getByRole("button", { name: /go to sign in/i });
    expect(loginLink).toHaveAttribute("href", "/login");
    // No password form left on screen, and nothing auto-navigates.
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("shows the generic invalid state if acceptance is rejected as no-longer-valid", async () => {
    validateMock.mockResolvedValueOnce(VALID_INVITATION);
    acceptMock.mockRejectedValueOnce(
      new ApiError({
        code: "RESOURCE_NOT_FOUND",
        message: "This invitation link is invalid or has expired.",
        status: 404,
      }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<AcceptInviteContent />);
    await screen.findByLabelText("Password");

    await user.type(screen.getByLabelText("Password"), "correct-horse-1");
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-1");
    await user.click(screen.getByRole("button", { name: /set password/i }));

    expect(await screen.findByText(/invalid or has expired/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("shows a toast (not the generic screen) when acceptance fails for an infrastructure reason, and keeps the form usable", async () => {
    validateMock.mockResolvedValueOnce(VALID_INVITATION);
    acceptMock.mockRejectedValueOnce(
      new ApiError({ code: "INTERNAL_ERROR", message: "An unexpected error occurred.", status: 500 }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<AcceptInviteContent />);
    await screen.findByLabelText("Password");

    await user.type(screen.getByLabelText("Password"), "correct-horse-1");
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-1");
    await user.click(screen.getByRole("button", { name: /set password/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("An unexpected error occurred."),
    );
    // The form is still there — the user can just try again.
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("disables the submit button while the acceptance request is pending", async () => {
    validateMock.mockResolvedValueOnce(VALID_INVITATION);
    let resolveAccept!: (value: { email: string; full_name: string }) => void;
    acceptMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveAccept = resolve;
      }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<AcceptInviteContent />);
    await screen.findByLabelText("Password");

    await user.type(screen.getByLabelText("Password"), "correct-horse-1");
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-1");
    await user.click(screen.getByRole("button", { name: /set password/i }));

    expect(await screen.findByRole("button", { name: /creating your account/i })).toBeDisabled();

    resolveAccept({ email: "ivy@example.com", full_name: "Ivy Invitee" });
  });

  it("does not submit an invalid password form (client-side validation blocks the API call)", async () => {
    validateMock.mockResolvedValueOnce(VALID_INVITATION);
    const user = userEvent.setup();
    renderWithQueryClient(<AcceptInviteContent />);
    await screen.findByLabelText("Password");

    await user.click(screen.getByRole("button", { name: /set password/i }));

    expect(await screen.findByText(/password must be at least 8 characters/i)).toBeInTheDocument();
    expect(acceptMock).not.toHaveBeenCalled();
  });
});
