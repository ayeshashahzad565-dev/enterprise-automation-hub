"use client";

import { useQuery } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";

export function useCompanies({
  includeDeleted = false,
  page = 1,
  pageSize = 20,
}: {
  includeDeleted?: boolean;
  page?: number;
  pageSize?: number;
}) {
  return useQuery({
    queryKey: platformKeys.companiesList({ includeDeleted, page, pageSize }),
    queryFn: () => platformService.listCompanies({ includeDeleted, page, pageSize }),
    staleTime: 15_000,
  });
}
