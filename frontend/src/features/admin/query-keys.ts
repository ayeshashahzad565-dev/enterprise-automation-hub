/** Centralized TanStack Query key factory for the Platform Administration feature. */
export const adminKeys = {
  all: ["admin"] as const,
  usersByRole: (role: string, page: number, pageSize: number) =>
    [...adminKeys.all, "users", "role", role, page, pageSize] as const,
  usersSearch: (query: string, page: number, pageSize: number) =>
    [...adminKeys.all, "users", "search", query, page, pageSize] as const,
  user: (id: string) => [...adminKeys.all, "users", "detail", id] as const,
  userActivity: (id: string, page: number) =>
    [...adminKeys.all, "users", "detail", id, "activity", page] as const,
  roles: () => [...adminKeys.all, "roles"] as const,
  departments: () => [...adminKeys.all, "departments"] as const,
  departmentWorkload: (department: string) =>
    [...adminKeys.all, "departments", department, "workload"] as const,
  settings: () => [...adminKeys.all, "settings"] as const,
  dashboard: () => [...adminKeys.all, "dashboard"] as const,
  invitations: () => [...adminKeys.all, "invitations"] as const,
  invitationsList: (params: {
    status?: string;
    query?: string;
    page: number;
    pageSize: number;
  }) => [...adminKeys.invitations(), "list", params] as const,
  jobs: () => [...adminKeys.all, "jobs"] as const,
  jobsList: (params: {
    status?: string;
    taskType?: string;
    queueName?: string;
    priority?: string;
    page: number;
    pageSize: number;
  }) => [...adminKeys.jobs(), "list", params] as const,
  job: (id: string) => [...adminKeys.jobs(), "detail", id] as const,
  jobsDeadLetter: (params: { taskType?: string; page: number; pageSize: number }) =>
    [...adminKeys.jobs(), "dead-letter", params] as const,
  jobsStats: () => [...adminKeys.jobs(), "stats"] as const,
  scheduledJobs: () => [...adminKeys.all, "scheduled-jobs"] as const,
};
