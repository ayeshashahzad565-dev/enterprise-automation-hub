"use client";

import { useQuery } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { requestService } from "@/services/request-service";

export function useRequest(id: string) {
  return useQuery({
    queryKey: requestKeys.detail(id),
    queryFn: () => requestService.get(id),
    staleTime: 10_000,
  });
}
