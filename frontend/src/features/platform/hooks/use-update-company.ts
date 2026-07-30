"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { platformKeys } from "@/features/platform/query-keys";
import { platformService } from "@/services/platform-service";
import type { UpdateCompanyBody } from "@/types/platform";

/** Backs both the companies list's suspend/reactivate row action and the
 * company detail page's settings-form save — a company's `is_active`
 * suspension and its `name`/`contact_email`/`notes` settings are the same
 * PATCH endpoint, so one mutation covers both call sites. */
export function useUpdateCompany() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateCompanyBody }) =>
      platformService.updateCompany(id, body),
    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: platformKeys.companies() });
      queryClient.invalidateQueries({ queryKey: platformKeys.company(variables.id) });
    },
  });
}
