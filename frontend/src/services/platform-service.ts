import { apiClient } from "@/lib/api/client";
import type {
  Company,
  CompanyLicense,
  CompanyLicenseUpdateBody,
  CreateCompanyBody,
  CreateFeatureFlagBody,
  FeatureFlag,
  PlatformAuditEntry,
  PlatformAuditLogFilters,
  PlatformHealth,
  PlatformStats,
  UpdateCompanyBody,
  UpdateFeatureFlagBody,
} from "@/types/platform";

function buildQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const platformService = {
  createCompany: (body: CreateCompanyBody) => apiClient.post<Company>("/platform/companies", body),
  listCompanies: (params: { includeDeleted?: boolean; page?: number; pageSize?: number }) =>
    apiClient.getList<Company>(
      `/platform/companies${buildQuery({
        include_deleted: params.includeDeleted,
        page: params.page,
        page_size: params.pageSize,
      })}`,
    ),
  getCompany: (id: string) => apiClient.get<Company>(`/platform/companies/${id}`),
  updateCompany: (id: string, body: UpdateCompanyBody) =>
    apiClient.patch<Company>(`/platform/companies/${id}`, body),
  deleteCompany: (id: string, expectedVersion: number) =>
    apiClient.delete<Company>(
      `/platform/companies/${id}${buildQuery({ expected_version: expectedVersion })}`,
    ),
  restoreCompany: (id: string, expectedVersion: number) =>
    apiClient.post<Company>(`/platform/companies/${id}/restore`, {
      expected_version: expectedVersion,
    }),
  getCompanyLicense: (id: string) => apiClient.get<CompanyLicense | null>(`/platform/companies/${id}/license`),
  updateCompanyLicense: (id: string, body: CompanyLicenseUpdateBody) =>
    apiClient.patch<CompanyLicense>(`/platform/companies/${id}/license`, body),
  listFeatureFlags: () => apiClient.get<FeatureFlag[]>("/platform/feature-flags"),
  createFeatureFlag: (body: CreateFeatureFlagBody) =>
    apiClient.post<FeatureFlag>("/platform/feature-flags", body),
  updateFeatureFlag: (key: string, body: UpdateFeatureFlagBody) =>
    apiClient.patch<FeatureFlag>(`/platform/feature-flags/${encodeURIComponent(key)}`, body),
  getStats: () => apiClient.get<PlatformStats>("/platform/stats"),
  getHealth: () => apiClient.get<PlatformHealth>("/platform/health"),
  listAuditLog: (params: PlatformAuditLogFilters) =>
    apiClient.getList<PlatformAuditEntry>(
      `/platform/audit-log${buildQuery({
        company_id: params.company_id,
        actor_id: params.actor_id,
        action: params.action,
        created_after: params.created_after,
        created_before: params.created_before,
        page: params.page,
        page_size: params.page_size,
      })}`,
    ),
};
