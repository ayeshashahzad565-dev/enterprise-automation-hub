"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";
import type { CreateFeatureFlagBody } from "@/types/platform";

export function useCreateFeatureFlag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CreateFeatureFlagBody) => platformService.createFeatureFlag(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: platformKeys.featureFlags() });
    },
  });
}
