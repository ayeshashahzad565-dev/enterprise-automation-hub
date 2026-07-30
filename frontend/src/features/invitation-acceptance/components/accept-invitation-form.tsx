"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { FormFieldError } from "@/components/patterns/form-field-error";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  acceptInvitationSchema,
  type AcceptInvitationFormValues,
} from "@/features/invitation-acceptance/schemas/accept-invitation-schema";

/** Presentational — the parent (`AcceptInviteContent`) owns the actual
 * `useAcceptInvitation` mutation, since it also needs the mutation's
 * outcome to decide whether to swap the whole panel to the success or
 * generic-invalid screen. This form only validates shape and hands back
 * a submitted password. */
export function AcceptInvitationForm({
  isSubmitting,
  onSubmit,
}: {
  isSubmitting: boolean;
  onSubmit: (password: string) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AcceptInvitationFormValues>({
    resolver: zodResolver(acceptInvitationSchema),
  });

  return (
    <form
      onSubmit={handleSubmit((values) => onSubmit(values.password))}
      className="space-y-4"
      noValidate
    >
      <div className="space-y-2">
        <Label htmlFor="accept-invite-password">Password</Label>
        <Input
          id="accept-invite-password"
          type="password"
          autoComplete="new-password"
          aria-invalid={!!errors.password}
          aria-describedby={errors.password ? "accept-invite-password-error" : undefined}
          {...register("password")}
        />
        <FormFieldError id="accept-invite-password-error" message={errors.password?.message} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="accept-invite-confirm-password">Confirm password</Label>
        <Input
          id="accept-invite-confirm-password"
          type="password"
          autoComplete="new-password"
          aria-invalid={!!errors.confirmPassword}
          aria-describedby={
            errors.confirmPassword ? "accept-invite-confirm-password-error" : undefined
          }
          {...register("confirmPassword")}
        />
        <FormFieldError
          id="accept-invite-confirm-password-error"
          message={errors.confirmPassword?.message}
        />
      </div>

      <Button type="submit" className="w-full" disabled={isSubmitting}>
        {isSubmitting ? "Creating your account..." : "Set password & join"}
      </Button>
    </form>
  );
}
