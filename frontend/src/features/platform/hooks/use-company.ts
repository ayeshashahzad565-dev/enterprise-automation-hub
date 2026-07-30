"use client";

import { useQuery } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";

export function useCompany(id: string) {
  return useQuery({
    queryKey: platformKeys.company(id),
    queryFn: () => platformService.getCompany(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  });
}
