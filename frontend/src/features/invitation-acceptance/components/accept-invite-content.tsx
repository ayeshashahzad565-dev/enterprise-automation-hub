"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { ErrorState } from "@/components/patterns/error-state";
import { PageTitle } from "@/components/patterns/typography";
import { AcceptInvitationForm } from "@/features/invitation-acceptance/components/accept-invitation-form";
import { AcceptInviteSkeleton } from "@/features/invitation-acceptance/components/accept-invite-skeleton";
import { AcceptInviteSuccess } from "@/features/invitation-acceptance/components/accept-invite-success";
import { InvitationPreview } from "@/features/invitation-acceptance/components/invitation-preview";
import { useAcceptInvitation } from "@/features/invitation-acceptance/hooks/use-accept-invitation";
import { useValidateInvitation } from "@/features/invitation-acceptance/hooks/use-validate-invitation";
import { ApiError } from "@/lib/api/errors";
import { notifyError } from "@/lib/toast";
import type { AcceptInvitationResult } from "@/types/invitation";

/** The one message shown for every reason a token might not be
 * acceptable (unknown, expired, revoked, already accepted, malformed) —
 * deliberately never more specific than this, preserving the backend's
 * anti-enumeration behavior (`app.api.routers.public_invitations`'s own
 * module docstring) at this layer too: even if a future bug made the
 * backend's error message more specific, this page does not read or
 * display it for this case. */
const GENERIC_INVALID_MESSAGE =
  "This invitation link is invalid or has expired. Please contact your administrator for a new invitation.";

const INFRASTRUCTURE_ERROR_MESSAGE =
  "Something went wrong on our end. Please try again in a moment.";

function isGenericInvalidError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export function AcceptInviteContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  // Set only when a *submitted acceptance* (not the initial validation)
  // is rejected as no-longer-acceptable — a genuine race between this
  // page loading and the invitation being revoked/expiring/already being
  // accepted elsewhere in the meantime. Checked ahead of the validate
  // query's own state so the page swaps to the generic screen instead of
  // re-showing a form that would just fail the same way again.
  const [raceInvalidated, setRaceInvalidated] = useState(false);
  const [acceptedResult, setAcceptedResult] = useState<AcceptInvitationResult | null>(null);

  const validateQuery = useValidateInvitation(token);
  const acceptMutation = useAcceptInvitation();

  async function handleSubmit(password: string) {
    if (!token) return;
    try {
      const result = await acceptMutation.mutateAsync({ token, password });
      setAcceptedResult(result);
    } catch (error) {
      if (isGenericInvalidError(error)) {
        setRaceInvalidated(true);
        return;
      }
      notifyError(error, INFRASTRUCTURE_ERROR_MESSAGE);
    }
  }

  if (acceptedResult) {
    return <AcceptInviteSuccess fullName={acceptedResult.full_name} />;
  }

  if (!token || raceInvalidated) {
    return (
      <div className="space-y-6">
        <PageTitle>Accept your invitation</PageTitle>
        <ErrorState message={GENERIC_INVALID_MESSAGE} />
      </div>
    );
  }

  if (validateQuery.isPending) {
    return <AcceptInviteSkeleton />;
  }

  if (validateQuery.isError) {
    if (isGenericInvalidError(validateQuery.error)) {
      return (
        <div className="space-y-6">
          <PageTitle>Accept your invitation</PageTitle>
          <ErrorState message={GENERIC_INVALID_MESSAGE} />
        </div>
      );
    }
    return (
      <div className="space-y-6">
        <PageTitle>Accept your invitation</PageTitle>
        <ErrorState
          message={INFRASTRUCTURE_ERROR_MESSAGE}
          onRetry={() => validateQuery.refetch()}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1.5 text-center md:text-left">
        <PageTitle>Welcome to Automata</PageTitle>
        <p className="text-sm text-muted-foreground">
          Confirm your details and choose a password to activate your account.
        </p>
      </div>
      <InvitationPreview invitation={validateQuery.data} />
      <AcceptInvitationForm isSubmitting={acceptMutation.isPending} onSubmit={handleSubmit} />
    </div>
  );
}
