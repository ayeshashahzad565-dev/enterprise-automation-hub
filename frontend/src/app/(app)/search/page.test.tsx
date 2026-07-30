import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SearchPage from "@/app/(app)/search/page";
import { renderWithQueryClient } from "@/test/test-utils";
import type { SearchResult } from "@/types/search";

vi.mock("@/services/search-service", () => ({
  searchService: {
    search: vi.fn(),
    listSavedFilters: vi.fn(),
    createSavedFilter: vi.fn(),
    deleteSavedFilter: vi.fn(),
    listSearchHistory: vi.fn(),
    clearSearchHistory: vi.fn(),
  },
}));

vi.mock("@/features/profile/hooks/use-current-user", () => ({
  useCurrentUser: () => ({ data: { role: "employee" } }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { searchService } from "@/services/search-service";

const searchMock = vi.mocked(searchService.search);
const listSavedFiltersMock = vi.mocked(searchService.listSavedFilters);
const listSearchHistoryMock = vi.mocked(searchService.listSearchHistory);

function buildResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    entity_type: "request",
    id: "result-1",
    title: "Laptop purchase",
    subtitle: "Expense Reimbursement · Pending",
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
    pagination: { page: 1, page_size: 20, total_records: items.length, total_pages: 1 },
  };
}

describe("SearchPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSavedFiltersMock.mockResolvedValue([]);
    listSearchHistoryMock.mockResolvedValue([]);
  });

  it("shows recent searches instead of results when the query is empty", async () => {
    listSearchHistoryMock.mockResolvedValue([
      { id: "h1", query_text: "widgets", entity_types: null, result_count: 3, created_at: "2026-07-20T00:00:00Z" },
    ]);

    renderWithQueryClient(<SearchPage />);

    expect(await screen.findByText("widgets")).toBeInTheDocument();
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("searches and renders grouped, highlighted results as the user types", async () => {
    searchMock.mockResolvedValue(pageOf([buildResult()]));
    const user = userEvent.setup();

    renderWithQueryClient(<SearchPage />);
    await user.type(screen.getByLabelText("Search"), "laptop");

    expect(await screen.findByText("Laptop purchase")).toBeInTheDocument();
    await waitFor(() => expect(searchMock).toHaveBeenCalledWith(
      expect.objectContaining({ q: "laptop" }),
    ));
  });

  it("shows an empty state when a search returns nothing", async () => {
    searchMock.mockResolvedValue(pageOf([]));
    const user = userEvent.setup();

    renderWithQueryClient(<SearchPage />);
    await user.type(screen.getByLabelText("Search"), "zzz");

    expect(await screen.findByText("No results")).toBeInTheDocument();
  });

  it("shows an error state and can retry", async () => {
    searchMock.mockRejectedValueOnce(new Error("network error"));
    searchMock.mockResolvedValueOnce(pageOf([buildResult()]));
    const user = userEvent.setup();

    renderWithQueryClient(<SearchPage />);
    await user.type(screen.getByLabelText("Search"), "laptop");

    expect(await screen.findByText("Couldn't run this search.")).toBeInTheDocument();
  });

  it("narrows results with an entity-type filter", async () => {
    searchMock.mockResolvedValue(pageOf([buildResult()]));
    const user = userEvent.setup();

    renderWithQueryClient(<SearchPage />);
    await user.click(screen.getByRole("checkbox", { name: "Request" }));
    await user.type(screen.getByLabelText("Search"), "laptop");

    await waitFor(() =>
      expect(searchMock).toHaveBeenCalledWith(expect.objectContaining({ entityTypes: ["request"] })),
    );
  });

  it("hides admin-only entity-type filters for a non-admin", async () => {
    renderWithQueryClient(<SearchPage />);

    expect(screen.queryByLabelText("User")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Department")).not.toBeInTheDocument();
  });
});
