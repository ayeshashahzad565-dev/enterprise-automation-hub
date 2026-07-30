"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { EmptyState } from "@/components/patterns/empty-state";
import { FormFieldError } from "@/components/patterns/form-field-error";
import { Caption } from "@/components/patterns/typography";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateCompanyLicense } from "@/features/platform/hooks/use-update-company-license";
import {
  companyLicenseSchema,
  type CompanyLicenseFormValues,
} from "@/features/platform/schemas/company-license-schema";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { CompanyLicense } from "@/types/platform";
import { ShieldCheck } from "lucide-react";

/** `expires_at` round-trips through an `<input type="date">`, so the
 * ISO datetime the API returns is truncated to its date portion for the
 * form, and re-expanded to a full ISO datetime on submit (midnight UTC)
 * — this license is purely informational (nothing enforces it), so the
 * time-of-day precision doesn't matter to anyone reading it. */
function toDateInputValue(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

function toFormValues(license: CompanyLicense | null): CompanyLicenseFormValues {
  return {
    plan_tier: license?.plan_tier ?? "",
    seat_limit: license?.seat_limit != null ? String(license.seat_limit) : "",
    expires_at: toDateInputValue(license?.expires_at ?? null),
    notes: license?.notes ?? "",
  };
}

export function CompanyLicensePanel({
  companyId,
  license,
}: {
  companyId: string;
  license: CompanyLicense | null;
}) {
  const updateLicense = useUpdateCompanyLicense();
  const form = useForm<CompanyLicenseFormValues>({
    resolver: zodResolver(companyLicenseSchema),
    defaultValues: toFormValues(license),
  });

  useEffect(() => {
    form.reset(toFormValues(license));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [license]);

  async function handleSubmit(values: CompanyLicenseFormValues) {
    try {
      await updateLicense.mutateAsync({
        id: companyId,
        body: {
          plan_tier: values.plan_tier,
          seat_limit: values.seat_limit ? Number(values.seat_limit) : null,
          expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null,
          notes: values.notes,
        },
      });
      notifySuccess("License updated.");
    } catch (error) {
      notifyError(error, "Couldn't update this license.");
    }
  }

  if (!license) {
    return (
      <div className="space-y-4">
        <EmptyState
          icon={ShieldCheck}
          title="No license configured"
          description="Set up a plan tier and seat limit for this company."
        />
        <LicenseForm form={form} onSubmit={handleSubmit} isPending={updateLicense.isPending} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">
          Seats used: {license.seats_used}
          {license.seat_limit != null ? ` / ${license.seat_limit}` : " / unlimited"}
        </Badge>
        {license.is_expired && <Badge variant="status-rejected">Expired</Badge>}
      </div>
      <LicenseForm form={form} onSubmit={handleSubmit} isPending={updateLicense.isPending} />
    </div>
  );
}

function LicenseForm({
  form,
  onSubmit,
  isPending,
}: {
  form: ReturnType<typeof useForm<CompanyLicenseFormValues>>;
  onSubmit: (values: CompanyLicenseFormValues) => void;
  isPending: boolean;
}) {
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
      <div className="space-y-2">
        <Label htmlFor="license-plan-tier">Plan tier</Label>
        <Input
          id="license-plan-tier"
          placeholder="free, pro, enterprise..."
          aria-invalid={!!form.formState.errors.plan_tier}
          aria-describedby={form.formState.errors.plan_tier ? "license-plan-tier-error" : undefined}
          {...form.register("plan_tier")}
        />
        <FormFieldError
          id="license-plan-tier-error"
          message={form.formState.errors.plan_tier?.message}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="license-seat-limit">Seat limit</Label>
        <Input
          id="license-seat-limit"
          inputMode="numeric"
          placeholder="Leave blank for unlimited"
          aria-invalid={!!form.formState.errors.seat_limit}
          aria-describedby={form.formState.errors.seat_limit ? "license-seat-limit-error" : undefined}
          {...form.register("seat_limit")}
        />
        <FormFieldError
          id="license-seat-limit-error"
          message={form.formState.errors.seat_limit?.message}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="license-expires-at">Expires</Label>
        <Input id="license-expires-at" type="date" {...form.register("expires_at")} />
        <Caption>Leave blank for no expiry.</Caption>
      </div>
      <div className="space-y-2">
        <Label htmlFor="license-notes">Notes</Label>
        <Textarea id="license-notes" rows={3} {...form.register("notes")} />
      </div>
      <div className="flex justify-end">
        <Button type="submit" disabled={isPending}>
          {isPending ? "Saving…" : "Save license"}
        </Button>
      </div>
    </form>
  );
}
