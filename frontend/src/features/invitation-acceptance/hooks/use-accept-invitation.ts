"use client";

import { useMutation } from "@tanstack/react-query";

import { invitationService } from "@/services/invitation-service";

export function useAcceptInvitation() {
  return useMutation({
    mutationFn: invitationService.accept,
  });
}
