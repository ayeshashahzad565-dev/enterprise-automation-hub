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
import { useCreateCompany } from "@/features/platform/hooks/use-create-company";
import {
  companyCreateSchema,
  type CompanyCreateFormValues,
} from "@/features/platform/schemas/company-create-schema";
import { notifyError, notifySuccess } from "@/lib/toast";

const DEFAULT_VALUES: CompanyCreateFormValues = { name: "" };

export function CreateCompanyDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const createCompany = useCreateCompany();
  const form = useForm<CompanyCreateFormValues>({
    resolver: zodResolver(companyCreateSchema),
    defaultValues: DEFAULT_VALUES,
  });

  useEffect(() => {
    if (open) form.reset(DEFAULT_VALUES);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function handleSubmit(values: CompanyCreateFormValues) {
    try {
      const created = await createCompany.mutateAsync({ name: values.name });
      notifySuccess(`${created.name} created.`);
      onOpenChange(false);
    } catch (error) {
      notifyError(error, "Couldn't create this company.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New company</DialogTitle>
          <DialogDescription>
            A URL-safe slug is generated automatically from the name.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="company-name">Company name</Label>
            <Input
              id="company-name"
              aria-invalid={!!form.formState.errors.name}
              aria-describedby={form.formState.errors.name ? "company-name-error" : undefined}
              {...form.register("name")}
            />
            <FormFieldError id="company-name-error" message={form.formState.errors.name?.message} />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={createCompany.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createCompany.isPending}>
              {createCompany.isPending ? "Creating…" : "Create company"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
