"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { FormFieldError } from "@/components/patterns/form-field-error";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateInvitation } from "@/features/admin/hooks/use-create-invitation";
import {
  invitationCreateSchema,
  type InvitationCreateFormValues,
} from "@/features/admin/schemas/invitation-create-schema";
import { notifyError, notifySuccess } from "@/lib/toast";

const DEFAULT_VALUES: InvitationCreateFormValues = {
  full_name: "",
  email: "",
  role: "employee",
  department: "",
};

export function CreateInvitationDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const createInvitation = useCreateInvitation();
  const form = useForm<InvitationCreateFormValues>({
    resolver: zodResolver(invitationCreateSchema),
    defaultValues: DEFAULT_VALUES,
  });

  useEffect(() => {
    if (open) form.reset(DEFAULT_VALUES);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function handleSubmit(values: InvitationCreateFormValues) {
    try {
      await createInvitation.mutateAsync({
        full_name: values.full_name,
        email: values.email,
        role: values.role,
        department: values.department || undefined,
      });
      notifySuccess(`Invitation sent to ${values.email}.`);
      onOpenChange(false);
    } catch (error) {
      notifyError(error, "Couldn't send this invitation.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a new user</DialogTitle>
          <DialogDescription>
            They&apos;ll receive an email with a link to set their password and join.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="invitation-full-name">Full name</Label>
            <Input
              id="invitation-full-name"
              aria-invalid={!!form.formState.errors.full_name}
              aria-describedby={
                form.formState.errors.full_name ? "invitation-full-name-error" : undefined
              }
              {...form.register("full_name")}
            />
            <FormFieldError
              id="invitation-full-name-error"
              message={form.formState.errors.full_name?.message}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invitation-email">Email</Label>
            <Input
              id="invitation-email"
              type="email"
              aria-invalid={!!form.formState.errors.email}
              aria-describedby={form.formState.errors.email ? "invitation-email-error" : undefined}
              {...form.register("email")}
            />
            <FormFieldError
              id="invitation-email-error"
              message={form.formState.errors.email?.message}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invitation-role">Role</Label>
            <Select
              value={form.watch("role")}
              onValueChange={(value) =>
                form.setValue("role", value as InvitationCreateFormValues["role"], {
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger id="invitation-role" className="w-full">
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
            <Label htmlFor="invitation-department">Department</Label>
            <Input
              id="invitation-department"
              aria-invalid={!!form.formState.errors.department}
              aria-describedby={
                form.formState.errors.department ? "invitation-department-error" : undefined
              }
              {...form.register("department")}
            />
            <FormFieldError
              id="invitation-department-error"
              message={form.formState.errors.department?.message}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={createInvitation.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createInvitation.isPending}>
              {createInvitation.isPending ? "Sending…" : "Send invitation"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
