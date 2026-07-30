"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";
import type { CreateCompanyBody } from "@/types/platform";

export function useCreateCompany() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CreateCompanyBody) => platformService.createCompany(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: platformKeys.companies() });
    },
  });
}
