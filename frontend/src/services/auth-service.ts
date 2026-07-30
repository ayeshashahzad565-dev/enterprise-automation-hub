import { apiClient } from "@/lib/api/client";
import type { Profile } from "@/types/profile";

export const authService = {
  getCurrentUser: () => apiClient.get<Profile>("/auth/me"),
};
