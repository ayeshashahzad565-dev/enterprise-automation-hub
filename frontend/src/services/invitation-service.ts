import { apiClient } from "@/lib/api/client";
import type { AcceptInvitationBody, AcceptInvitationResult, InvitationValidation } from "@/types/invitation";

/**
 * Wraps the public, unauthenticated `/api/v1/invitations/*` endpoints
 * (Milestone 6) — kept separate from `admin-service.ts` since these
 * calls carry no bearer token and are never gated by an admin role;
 * `apiClient` still attaches one automatically if the caller happens to
 * have an existing Supabase session (e.g. an admin previewing this page),
 * but the backend never inspects it for these two routes.
 */
export const invitationService = {
  validate: (token: string) =>
    apiClient.get<InvitationValidation>(
      `/invitations/validate?token=${encodeURIComponent(token)}`,
    ),
  accept: (body: AcceptInvitationBody) =>
    apiClient.post<AcceptInvitationResult>("/invitations/accept", body),
};
