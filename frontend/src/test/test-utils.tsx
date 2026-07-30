import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

/** A fresh, retry-disabled `QueryClient` per test, matching this
 * project's real `createQueryClient` (`@/lib/query-client`) except with
 * retries off so a mocked rejection surfaces immediately instead of
 * being retried and timing the test out. */
export function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return {
    queryClient,
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
  };
}
