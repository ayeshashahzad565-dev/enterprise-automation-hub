/**
 * Frontend-owned types for the public, unauthenticated invitation
 * surface (`/api/v1/invitations/*`) — defined independently of the
 * backend's Pydantic schemas, matching the convention every other
 * `types/*.ts` file in this project follows.
 */

import type { UserRole } from "@/types/profile";

/** Mirrors `app.api.schemas.public_invitations.InvitationValidateOut`
 * exactly — deliberately minimal. The backend never returns the
 * invitation's id, status, version, or resend count to an unauthenticated
 * caller; there is nothing further to strip here. */
export interface InvitationValidation {
  email: string;
  full_name: string;
  role: UserRole;
  department: string | null;
  expires_at: string;
}

/** Mirrors `app.api.schemas.public_invitations.InvitationAcceptBody`. */
export interface AcceptInvitationBody {
  token: string;
  password: string;
}

/** Mirrors `app.api.schemas.public_invitations.InvitationAcceptOut`. */
export interface AcceptInvitationResult {
  email: string;
  full_name: string;
}
