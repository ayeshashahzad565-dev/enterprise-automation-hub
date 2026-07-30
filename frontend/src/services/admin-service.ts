import { apiClient } from "@/lib/api/client";
import type { AuditLogEntry } from "@/types/activity";
import type {
  AdminDashboard,
  AdminUser,
  CreateInvitationBody,
  DepartmentSummary,
  DepartmentWorkload,
  Invitation,
  InvitationStatus,
  PlatformSettings,
  RolePermissions,
  UpdateAdminUserBody,
} from "@/types/admin";
import type { Job, JobPriority, JobStatus, QueueStats, ScheduledJob } from "@/types/jobs";
import type { UserRole } from "@/types/profile";

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

export const adminService = {
  listUsersByRole: (role: UserRole, page = 1, pageSize = 20) =>
    apiClient.getList<AdminUser>(
      `/admin/users${buildQuery({ role, page, page_size: pageSize })}`,
    ),
  searchUsers: (query: string, page = 1, pageSize = 20) =>
    apiClient.getList<AdminUser>(
      `/admin/users${buildQuery({ query, page, page_size: pageSize })}`,
    ),
  getUser: (id: string) => apiClient.get<AdminUser>(`/admin/users/${id}`),
  updateUser: (id: string, body: UpdateAdminUserBody) =>
    apiClient.patch<AdminUser>(`/admin/users/${id}`, body),
  getUserActivity: (id: string, page = 1) =>
    apiClient.getList<AuditLogEntry>(`/admin/users/${id}/activity${buildQuery({ page })}`),
  listRoles: () => apiClient.get<RolePermissions[]>("/admin/roles"),
  listDepartments: () => apiClient.get<DepartmentSummary[]>("/admin/departments"),
  getDepartmentWorkload: (department: string) =>
    apiClient.get<DepartmentWorkload>(
      `/admin/departments/${encodeURIComponent(department)}/workload`,
    ),
  getSettings: () => apiClient.get<PlatformSettings>("/admin/settings"),
  getDashboard: () => apiClient.get<AdminDashboard>("/admin/dashboard"),
  listInvitations: (params: {
    status?: InvitationStatus;
    query?: string;
    page?: number;
    pageSize?: number;
  }) =>
    apiClient.getList<Invitation>(
      `/admin/invitations${buildQuery({
        status: params.status,
        query: params.query,
        page: params.page,
        page_size: params.pageSize,
      })}`,
    ),
  createInvitation: (body: CreateInvitationBody) =>
    apiClient.post<Invitation>("/admin/invitations", body),
  resendInvitation: (id: string) => apiClient.post<Invitation>(`/admin/invitations/${id}/resend`),
  revokeInvitation: (id: string) => apiClient.post<Invitation>(`/admin/invitations/${id}/revoke`),
  listJobs: (params: {
    status?: JobStatus;
    taskType?: string;
    queueName?: string;
    priority?: JobPriority;
    page?: number;
    pageSize?: number;
  }) =>
    apiClient.getList<Job>(
      `/admin/jobs${buildQuery({
        status: params.status,
        task_type: params.taskType,
        queue_name: params.queueName,
        priority: params.priority,
        page: params.page,
        page_size: params.pageSize,
      })}`,
    ),
  getJob: (id: string) => apiClient.get<Job>(`/admin/jobs/${id}`),
  listDeadLetterJobs: (params: { taskType?: string; page?: number; pageSize?: number }) =>
    apiClient.getList<Job>(
      `/admin/jobs/dead-letter${buildQuery({
        task_type: params.taskType,
        page: params.page,
        page_size: params.pageSize,
      })}`,
    ),
  retryJob: (id: string) => apiClient.post<Job>(`/admin/jobs/${id}/retry`),
  getQueueStats: () => apiClient.get<QueueStats>("/admin/jobs/stats/summary"),
  listScheduledJobs: () => apiClient.get<ScheduledJob[]>("/admin/scheduled-jobs"),
  enableScheduledJob: (name: string) =>
    apiClient.post<ScheduledJob | null>(`/admin/scheduled-jobs/${encodeURIComponent(name)}/enable`),
  disableScheduledJob: (name: string) =>
    apiClient.post<ScheduledJob | null>(`/admin/scheduled-jobs/${encodeURIComponent(name)}/disable`),
  triggerScheduledJob: (name: string) =>
    apiClient.post<{ triggered: boolean }>(
      `/admin/scheduled-jobs/${encodeURIComponent(name)}/trigger-now`,
    ),
};
