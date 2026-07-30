"use client";

import { useQuery } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";

export function useCompanyLicense(id: string) {
  return useQuery({
    queryKey: platformKeys.companyLicense(id),
    queryFn: () => platformService.getCompanyLicense(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  });
}
