import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AcceptInvitationForm } from "@/features/invitation-acceptance/components/accept-invitation-form";

describe("AcceptInvitationForm", () => {
  it("rejects an empty submission", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<AcceptInvitationForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: /set password/i }));

    expect(await screen.findByText(/password must be at least 8 characters/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a password shorter than 8 characters", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<AcceptInvitationForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Password"), "short1");
    await user.type(screen.getByLabelText("Confirm password"), "short1");
    await user.click(screen.getByRole("button", { name: /set password/i }));

    expect(await screen.findByText(/password must be at least 8 characters/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects mismatched passwords", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<AcceptInvitationForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Password"), "correct-horse-1");
    await user.type(screen.getByLabelText("Confirm password"), "different-horse-1");
    await user.click(screen.getByRole("button", { name: /set password/i }));

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the password once validation passes", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<AcceptInvitationForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Password"), "correct-horse-1");
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-1");
    await user.click(screen.getByRole("button", { name: /set password/i }));

    expect(onSubmit).toHaveBeenCalledWith("correct-horse-1");
  });

  it("disables the submit button while submitting", () => {
    render(<AcceptInvitationForm isSubmitting onSubmit={vi.fn()} />);

    expect(screen.getByRole("button", { name: /creating your account/i })).toBeDisabled();
  });

  it("marks an invalid field aria-invalid and links it to its error via aria-describedby", async () => {
    const user = userEvent.setup();
    render(<AcceptInvitationForm isSubmitting={false} onSubmit={vi.fn()} />);

    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("aria-invalid", "false");
    expect(password).not.toHaveAttribute("aria-describedby");

    await user.click(screen.getByRole("button", { name: /set password/i }));

    expect(password).toHaveAttribute("aria-invalid", "true");
    const describedBy = password.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const errorMessage = document.getElementById(describedBy as string);
    expect(errorMessage).toHaveAttribute("role", "alert");
    expect(errorMessage).toHaveTextContent(/password must be at least 8 characters/i);
  });
});
