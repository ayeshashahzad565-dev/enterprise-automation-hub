"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";
import type { UpdateFeatureFlagBody } from "@/types/platform";

export function useUpdateFeatureFlag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ key, body }: { key: string; body: UpdateFeatureFlagBody }) =>
      platformService.updateFeatureFlag(key, body),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: platformKeys.featureFlags() });
    },
  });
}
