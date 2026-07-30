"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/providers/auth-provider";
import { createClient } from "@/lib/supabase/client";
import { ROUTES } from "@/utils/constants";

function initialsFor(email: string | undefined): string {
  if (!email) return "?";
  return email.slice(0, 2).toUpperCase();
}

export function UserMenu() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuth();

  async function handleSignOut() {
    try {
      await createClient().auth.signOut();
    } catch {
      // Fall through to a hard redirect below regardless of whether the
      // Supabase call succeeded — a client-side query-cache clear plus a
      // full navigation to /login is safe either way, and this guarantees
      // the user is never stranded on an unauthenticated page waiting on
      // a rejected signOut() promise.
    } finally {
      queryClient.clear();
      router.push(ROUTES.login);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="relative h-9 w-9 rounded-full"
        aria-label="Account menu"
        render={<Button variant="ghost" />}
      >
        <Avatar className="h-9 w-9">
          <AvatarFallback>{initialsFor(user?.email)}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="truncate">{user?.email ?? "Account"}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={handleSignOut}>
          <LogOut className="mr-2 size-5" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
