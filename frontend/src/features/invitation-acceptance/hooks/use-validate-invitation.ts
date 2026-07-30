"use client";

import { useQuery } from "@tanstack/react-query";

import { invitationService } from "@/services/invitation-service";

/**
 * Validates a raw invitation token against the public
 * `GET /invitations/validate` endpoint. Disabled entirely when no token
 * is present (e.g. the link was opened without a `?token=` query
 * parameter) — there is nothing to look up, and an empty/missing token
 * should never even reach the network.
 */
export function useValidateInvitation(token: string | null) {
  return useQuery({
    queryKey: ["invitation-validate", token],
    queryFn: () => invitationService.validate(token as string),
    enabled: Boolean(token),
    retry: false,
    staleTime: Infinity,
  });
}
