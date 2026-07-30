"use client";

import { createContext, useContext, type ReactNode } from "react";

import { useAuthSession, type AuthSessionState } from "@/hooks/use-auth-session";

const AuthContext = createContext<AuthSessionState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const value = useAuthSession();
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthSessionState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
