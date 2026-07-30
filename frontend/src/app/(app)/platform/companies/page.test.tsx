import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PlatformCompaniesPage from "@/app/(app)/platform/companies/page";
import { ApiError } from "@/lib/api/errors";
import { renderWithQueryClient } from "@/test/test-utils";
import type { Company } from "@/types/platform";

vi.mock("@/services/platform-service", () => ({
  platformService: {
    listCompanies: vi.fn(),
    createCompany: vi.fn(),
    updateCompany: vi.fn(),
    deleteCompany: vi.fn(),
    restoreCompany: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { platformService } from "@/services/platform-service";
import { toast } from "sonner";

const listCompaniesMock = vi.mocked(platformService.listCompanies);
const createCompanyMock = vi.mocked(platformService.createCompany);
const updateCompanyMock = vi.mocked(platformService.updateCompany);
const deleteCompanyMock = vi.mocked(platformService.deleteCompany);

function buildCompany(overrides: Partial<Company> = {}): Company {
  return {
    id: "company-1",
    name: "Acme Corp",
    slug: "acme-corp-ab12cd34",
    is_active: true,
    contact_email: null,
    notes: null,
    version: 1,
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
    deleted_at: null,
    deleted_by: null,
    is_deleted: false,
    ...overrides,
  };
}

function pageOf(items: Company[]) {
  return {
    data: items,
    pagination: { page: 1, page_size: 20, total_records: items.length, total_pages: 1 },
  };
}

describe("PlatformCompaniesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an empty state with no companies", async () => {
    listCompaniesMock.mockResolvedValueOnce(pageOf([]));

    renderWithQueryClient(<PlatformCompaniesPage />);

    expect(await screen.findByText("No companies yet")).toBeInTheDocument();
  });

  it("renders companies once loaded", async () => {
    listCompaniesMock.mockResolvedValueOnce(pageOf([buildCompany()]));

    renderWithQueryClient(<PlatformCompaniesPage />);

    expect(await screen.findByText("Acme Corp")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("creates a new company from the dialog", async () => {
    listCompaniesMock.mockResolvedValue(pageOf([]));
    createCompanyMock.mockResolvedValueOnce(buildCompany());
    const user = userEvent.setup();

    renderWithQueryClient(<PlatformCompaniesPage />);
    await screen.findByText("No companies yet");

    await user.click(screen.getByRole("button", { name: /new company/i }));
    await user.type(screen.getByLabelText("Company name"), "Acme Corp");
    await user.click(screen.getByRole("button", { name: /^create company$/i }));

    await waitFor(() => expect(createCompanyMock).toHaveBeenCalledWith({ name: "Acme Corp" }));
    expect(toast.success).toHaveBeenCalledWith("Acme Corp created.");
  });

  it("asks for confirmation before suspending, and suspends after confirming", async () => {
    listCompaniesMock.mockResolvedValue(pageOf([buildCompany()]));
    updateCompanyMock.mockResolvedValueOnce(buildCompany({ is_active: false, version: 2 }));
    const user = userEvent.setup();

    renderWithQueryClient(<PlatformCompaniesPage />);
    await screen.findByText("Acme Corp");

    await user.click(screen.getByRole("button", { name: /open quick actions/i }));
    await user.click(await screen.findByText("Suspend"));
    expect(await screen.findByText("Suspend this company?")).toBeInTheDocument();

    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^suspend$/i }));

    await waitFor(() =>
      expect(updateCompanyMock).toHaveBeenCalledWith("company-1", {
        expected_version: 1,
        is_active: false,
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("Acme Corp suspended.");
  });

  it("surfaces the self-lockout 422 error from the server as a toast", async () => {
    listCompaniesMock.mockResolvedValue(pageOf([buildCompany()]));
    updateCompanyMock.mockRejectedValueOnce(
      new ApiError({
        code: "VALIDATION_ERROR",
        message: "You may not suspend your own company.",
        status: 422,
      }),
    );
    const user = userEvent.setup();

    renderWithQueryClient(<PlatformCompaniesPage />);
    await screen.findByText("Acme Corp");

    await user.click(screen.getByRole("button", { name: /open quick actions/i }));
    await user.click(await screen.findByText("Suspend"));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^suspend$/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("You may not suspend your own company."),
    );
  });

  it("deletes a company after confirmation", async () => {
    listCompaniesMock.mockResolvedValue(pageOf([buildCompany()]));
    deleteCompanyMock.mockResolvedValueOnce(buildCompany({ is_deleted: true, deleted_at: "2026-07-24T00:00:00Z" }));
    const user = userEvent.setup();

    renderWithQueryClient(<PlatformCompaniesPage />);
    await screen.findByText("Acme Corp");

    await user.click(screen.getByRole("button", { name: /open quick actions/i }));
    await user.click(await screen.findByText("Delete"));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deleteCompanyMock).toHaveBeenCalledWith("company-1", 1));
    expect(toast.success).toHaveBeenCalledWith("Acme Corp deleted.");
  });
});
