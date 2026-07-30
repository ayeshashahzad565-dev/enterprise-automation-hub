"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Caption, SectionHeading } from "@/components/patterns/typography";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { ActivityItem } from "@/features/activity/components/activity-item";
import { useUpdateAdminUser } from "@/features/admin/hooks/use-update-admin-user";
import { useUserActivity } from "@/features/admin/hooks/use-user-activity";
import {
  userEditSchema,
  type UserEditFormValues,
} from "@/features/admin/schemas/user-edit-schema";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { AdminUser } from "@/types/admin";

/**
 * Right-side detail panel: role/department assignment (the only mutable
 * fields — `Profile` has no account-status field, so there is nothing
 * else to toggle here) plus the user's own recent activity, reusing
 * Phase 5's `ActivityItem` row renderer.
 */
export function UserDetailPanel({
  user,
  open,
  onOpenChange,
}: {
  user: AdminUser | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: activity, isLoading: isActivityLoading } = useUserActivity(user?.id ?? "");
  const updateUser = useUpdateAdminUser();

  const form = useForm<UserEditFormValues>({
    resolver: zodResolver(userEditSchema),
    defaultValues: { role: user?.role ?? "employee", department: user?.department ?? "" },
  });

  useEffect(() => {
    form.reset({ role: user?.role ?? "employee", department: user?.department ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  async function handleSubmit(values: UserEditFormValues) {
    if (!user) return;
    try {
      await updateUser.mutateAsync({
        id: user.id,
        body: {
          expected_version: user.version,
          role: values.role,
          department: values.department,
        },
      });
      notifySuccess("User updated.");
    } catch (error) {
      notifyError(error, "Couldn't update this user.");
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-4 overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{user?.full_name ?? "User"}</SheetTitle>
        </SheetHeader>

        {user && (
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4 px-4" noValidate>
            <div className="space-y-2">
              <Label htmlFor="role">Role</Label>
              <Select
                value={form.watch("role")}
                onValueChange={(value) =>
                  form.setValue("role", value as UserEditFormValues["role"], {
                    shouldValidate: true,
                  })
                }
              >
                <SelectTrigger id="role" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="employee">Employee</SelectItem>
                  <SelectItem value="approver">Approver</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="department">Department</Label>
              <Input id="department" {...form.register("department")} />
              <Caption>Clearing this field sets the department to blank, not unassigned.</Caption>
            </div>
            <div className="flex justify-end">
              <Button type="submit" disabled={updateUser.isPending}>
                {updateUser.isPending ? "Saving..." : "Save changes"}
              </Button>
            </div>
          </form>
        )}

        <div className="space-y-2 px-4 pb-4">
          <SectionHeading>Recent activity</SectionHeading>
          <div className="space-y-1">
            {isActivityLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : activity && activity.data.length > 0 ? (
              activity.data.map((entry) => <ActivityItem key={entry.id} entry={entry} />)
            ) : (
              <p className="text-sm text-muted-foreground">No recorded activity yet.</p>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
