import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CommandPalette } from "@/components/patterns/command-palette";
import { renderWithQueryClient } from "@/test/test-utils";
import type { SearchResult } from "@/types/search";

const pushMock = vi.fn();

vi.mock("@/services/search-service", () => ({
  searchService: { search: vi.fn() },
}));

vi.mock("@/features/profile/hooks/use-current-user", () => ({
  useCurrentUser: () => ({ data: { role: "employee" } }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }),
}));

import { searchService } from "@/services/search-service";

const searchMock = vi.mocked(searchService.search);

function buildResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    entity_type: "request",
    id: "result-1",
    title: "Laptop purchase",
    subtitle: "Expense Reimbursement",
    snippet: "New **laptop** request",
    score: 0.95,
    created_at: "2026-07-20T00:00:00Z",
    request_id: "request-1",
    stage_id: null,
    stage_name: null,
    request_type: null,
    ...overrides,
  };
}

function pageOf(items: SearchResult[]) {
  return {
    data: items,
    pagination: { page: 1, page_size: 5, total_records: items.length, total_pages: 1 },
  };
}

describe("CommandPalette", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens on Ctrl+K and shows static navigation", async () => {
    renderWithQueryClient(<CommandPalette />);

    await userEvent.keyboard("{Control>}k{/Control}");

    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Requests")).toBeInTheDocument();
  });

  it("groups live search results by entity type and links to the full results page", async () => {
    searchMock.mockResolvedValue(pageOf([buildResult()]));
    const user = userEvent.setup();
    renderWithQueryClient(<CommandPalette />);
    await user.keyboard("{Control>}k{/Control}");

    await user.type(screen.getByPlaceholderText(/search everything/i), "laptop");

    expect(await screen.findByText("Laptop purchase")).toBeInTheDocument();
    expect(screen.getByText(/view all results for/i)).toBeInTheDocument();
  });

  it("navigates to a result when selected", async () => {
    searchMock.mockResolvedValue(pageOf([buildResult()]));
    const user = userEvent.setup();
    renderWithQueryClient(<CommandPalette />);
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByPlaceholderText(/search everything/i), "laptop");

    await user.click(await screen.findByText("Laptop purchase"));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/requests/request-1"));
  });

  it("does not search for a very short query", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<CommandPalette />);
    await user.keyboard("{Control>}k{/Control}");

    await user.type(screen.getByPlaceholderText(/search everything/i), "a");

    await new Promise((resolve) => setTimeout(resolve, 350));
    expect(searchMock).not.toHaveBeenCalled();
  });
});
