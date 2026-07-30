/** Centralized TanStack Query key factory for the Platform Administration feature. */
export const platformKeys = {
  all: ["platform"] as const,
  stats: () => [...platformKeys.all, "stats"] as const,
  health: () => [...platformKeys.all, "health"] as const,
  companies: () => [...platformKeys.all, "companies"] as const,
  companiesList: (params: { includeDeleted?: boolean; page: number; pageSize: number }) =>
    [...platformKeys.companies(), "list", params] as const,
  company: (id: string) => [...platformKeys.companies(), "detail", id] as const,
  companyLicense: (id: string) => [...platformKeys.companies(), "detail", id, "license"] as const,
  featureFlags: () => [...platformKeys.all, "feature-flags"] as const,
  auditLog: () => [...platformKeys.all, "audit-log"] as const,
  auditLogList: (params: object) => [...platformKeys.auditLog(), "list", params] as const,
};
