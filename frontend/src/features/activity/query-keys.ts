/** Centralized TanStack Query key factory for the Activity feature. */
export const activityKeys = {
  all: ["activity"] as const,
  organization: (params: object) => [...activityKeys.all, "organization", params] as const,
  mine: (params: object) => [...activityKeys.all, "mine", params] as const,
};
