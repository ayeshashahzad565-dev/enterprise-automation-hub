"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";
import type { CompanyLicenseUpdateBody } from "@/types/platform";

export function useUpdateCompanyLicense() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: CompanyLicenseUpdateBody }) =>
      platformService.updateCompanyLicense(id, body),
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: platformKeys.companyLicense(variables.id) });
    },
  });
}
