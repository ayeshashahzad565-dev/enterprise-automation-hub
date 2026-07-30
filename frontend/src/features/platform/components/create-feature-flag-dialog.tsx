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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useCreateFeatureFlag } from "@/features/platform/hooks/use-create-feature-flag";
import {
  featureFlagCreateSchema,
  type FeatureFlagCreateFormValues,
} from "@/features/platform/schemas/feature-flag-create-schema";
import { notifyError, notifySuccess } from "@/lib/toast";

const DEFAULT_VALUES: FeatureFlagCreateFormValues = { key: "", description: "", enabled: false };

export function CreateFeatureFlagDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const createFlag = useCreateFeatureFlag();
  const form = useForm<FeatureFlagCreateFormValues>({
    resolver: zodResolver(featureFlagCreateSchema),
    defaultValues: DEFAULT_VALUES,
  });

  useEffect(() => {
    if (open) form.reset(DEFAULT_VALUES);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function handleSubmit(values: FeatureFlagCreateFormValues) {
    try {
      await createFlag.mutateAsync(values);
      notifySuccess(`${values.key} created.`);
      onOpenChange(false);
    } catch (error) {
      notifyError(error, "Couldn't create this feature flag.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New feature flag</DialogTitle>
          <DialogDescription>A new flag always starts off unless enabled below.</DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="flag-key">Key</Label>
            <Input
              id="flag-key"
              placeholder="new_dashboard_layout"
              aria-invalid={!!form.formState.errors.key}
              aria-describedby={form.formState.errors.key ? "flag-key-error" : undefined}
              {...form.register("key")}
            />
            <FormFieldError id="flag-key-error" message={form.formState.errors.key?.message} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="flag-description">Description</Label>
            <Textarea
              id="flag-description"
              rows={3}
              aria-invalid={!!form.formState.errors.description}
              aria-describedby={
                form.formState.errors.description ? "flag-description-error" : undefined
              }
              {...form.register("description")}
            />
            <FormFieldError
              id="flag-description-error"
              message={form.formState.errors.description?.message}
            />
          </div>
          <div className="flex items-center justify-between rounded-md border p-3">
            <Label htmlFor="flag-enabled">Enabled</Label>
            <Switch
              id="flag-enabled"
              checked={form.watch("enabled")}
              onCheckedChange={(checked) => form.setValue("enabled", checked)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={createFlag.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createFlag.isPending}>
              {createFlag.isPending ? "Creating…" : "Create flag"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
