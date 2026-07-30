"use client";

import { DefinitionList, DefinitionRow } from "@/components/patterns/definition-list";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";

const ROLE_LABELS: Record<string, string> = {
  employee: "Employee",
  approver: "Approver",
  admin: "Administrator",
};

export function ProfileCard() {
  const { data: profile, isLoading, isError, error } = useCurrentUser();

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Your profile</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-40" />
        </CardContent>
      </Card>
    );
  }

  if (isError || !profile) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Your profile</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive">
            {error instanceof Error ? error.message : "Failed to load your profile."}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your profile</CardTitle>
      </CardHeader>
      <CardContent>
        <DefinitionList>
          <DefinitionRow label="Name">{profile.full_name}</DefinitionRow>
          <DefinitionRow label="Role">{ROLE_LABELS[profile.role] ?? profile.role}</DefinitionRow>
          <DefinitionRow label="Department">{profile.department ?? "—"}</DefinitionRow>
        </DefinitionList>
      </CardContent>
    </Card>
  );
}
