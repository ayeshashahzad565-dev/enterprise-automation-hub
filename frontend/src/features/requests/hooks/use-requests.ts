"use client";

import { useQuery } from "@tanstack/react-query";

import { requestKeys } from "@/features/requests/query-keys";
import { requestService, type ListRequestsParams } from "@/services/request-service";

export function useRequests(params: ListRequestsParams) {
  return useQuery({
    queryKey: requestKeys.list(params),
    queryFn: () => requestService.list(params),
    staleTime: 30_000,
    placeholderData: (previousData) => previousData,
  });
}
