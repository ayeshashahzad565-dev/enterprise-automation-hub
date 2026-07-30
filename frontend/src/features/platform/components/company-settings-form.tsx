"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { FormFieldError } from "@/components/patterns/form-field-error";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateCompany } from "@/features/platform/hooks/use-update-company";
import {
  companySettingsSchema,
  type CompanySettingsFormValues,
} from "@/features/platform/schemas/company-settings-schema";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { Company } from "@/types/platform";

/** Contact email + notes editor — the two mutable settings fields beyond
 * name/active status (which the companies list's row actions and rename
 * flow already cover), following `UserDetailPanel`'s exact
 * form/`expected_version` shape. */
export function CompanySettingsForm({ company }: { company: Company }) {
  const updateCompany = useUpdateCompany();
  const form = useForm<CompanySettingsFormValues>({
    resolver: zodResolver(companySettingsSchema),
    defaultValues: {
      contact_email: company.contact_email ?? "",
      notes: company.notes ?? "",
    },
  });

  useEffect(() => {
    form.reset({ contact_email: company.contact_email ?? "", notes: company.notes ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  async function handleSubmit(values: CompanySettingsFormValues) {
    try {
      await updateCompany.mutateAsync({
        id: company.id,
        body: {
          expected_version: company.version,
          contact_email: values.contact_email || undefined,
          notes: values.notes,
        },
      });
      notifySuccess("Company settings updated.");
    } catch (error) {
      notifyError(error, "Couldn't update this company.");
    }
  }

  return (
    <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4" noValidate>
      <div className="space-y-2">
        <Label htmlFor="company-contact-email">Contact email</Label>
        <Input
          id="company-contact-email"
          type="email"
          aria-invalid={!!form.formState.errors.contact_email}
          aria-describedby={
            form.formState.errors.contact_email ? "company-contact-email-error" : undefined
          }
          {...form.register("contact_email")}
        />
        <FormFieldError
          id="company-contact-email-error"
          message={form.formState.errors.contact_email?.message}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="company-notes">Notes</Label>
        <Textarea id="company-notes" rows={4} {...form.register("notes")} />
      </div>
      <div className="flex justify-end">
        <Button type="submit" disabled={updateCompany.isPending}>
          {updateCompany.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
