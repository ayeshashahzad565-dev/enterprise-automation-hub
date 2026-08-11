/** Dispatched by the header's visible search button; `CommandPalette`
 * listens for it alongside its own Cmd/Ctrl+K keydown handler, so the
 * palette can be opened from a discoverable button, not just the
 * shortcut. */
export const OPEN_COMMAND_PALETTE_EVENT = "open-command-palette";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

if (process.env.NODE_ENV === "development" && !process.env.NEXT_PUBLIC_API_BASE_URL) {
  // Deliberate, dev-only configuration warning.
  console.warn(
    "[config] NEXT_PUBLIC_API_BASE_URL is not set — falling back to " +
      `"${API_BASE_URL}". Set it in frontend/.env.local (see ` +
      ".env.local.example) if your backend isn't running on that default.",
  );
}

export const ROUTES = {
  home: "/",
  login: "/login",
  dashboard: "/dashboard",
  unauthorized: "/unauthorized",
  requests: "/requests",
  newRequest: "/requests/new",
  request: (id: string) => `/requests/${id}`,
  approvals: "/approvals",
  approval: (stageId: string) => `/approvals/${stageId}`,
  analytics: "/analytics",
  notifications: "/notifications",
  notificationPreferences: "/notifications/preferences",
  activity: "/activity",
  workflows: "/workflows",
  workflow: (requestType: string, version: number) =>
    `/workflows/${encodeURIComponent(requestType)}/${version}`,
  admin: "/admin",
  adminUsers: "/admin/users",
  adminInvitations: "/admin/invitations",
  adminRoles: "/admin/roles",
  adminDepartments: "/admin/departments",
  adminJobs: "/admin/jobs",
  adminSettings: "/admin/settings",
  search: "/search",
  searchWithQuery: (q: string) => `/search?q=${encodeURIComponent(q)}`,
  platform: "/platform",
  platformCompanies: "/platform/companies",
  platformCompany: (id: string) => `/platform/companies/${id}`,
  platformAudit: "/platform/audit",
  platformHealth: "/platform/health",
  platformFeatureFlags: "/platform/feature-flags",
} as const;
