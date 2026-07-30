/** Centralized TanStack Query key factory for the Notifications feature. */
export const notificationKeys = {
  all: ["notifications"] as const,
  lists: () => [...notificationKeys.all, "list"] as const,
  list: (params: object) => [...notificationKeys.lists(), params] as const,
  infiniteLists: () => [...notificationKeys.all, "infinite-list"] as const,
  infiniteList: (params: object) => [...notificationKeys.infiniteLists(), params] as const,
  unreadCount: () => [...notificationKeys.all, "unread-count"] as const,
  preferences: () => [...notificationKeys.all, "preferences"] as const,
};
