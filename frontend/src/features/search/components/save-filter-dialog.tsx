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
import { useCreateSavedFilter } from "@/features/search/hooks/use-create-saved-filter";
import { saveFilterSchema, type SaveFilterFormValues } from "@/features/search/schemas/save-filter-schema";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { SearchEntityType } from "@/types/search";

const DEFAULT_VALUES: SaveFilterFormValues = { name: "" };

export function SaveFilterDialog({
  open,
  onOpenChange,
  queryText,
  entityTypes,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  queryText: string;
  entityTypes: SearchEntityType[];
}) {
  const createSavedFilter = useCreateSavedFilter();
  const form = useForm<SaveFilterFormValues>({
    resolver: zodResolver(saveFilterSchema),
    defaultValues: DEFAULT_VALUES,
  });

  useEffect(() => {
    if (open) form.reset(DEFAULT_VALUES);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function handleSubmit(values: SaveFilterFormValues) {
    try {
      await createSavedFilter.mutateAsync({
        name: values.name,
        query_text: queryText,
        entity_types: entityTypes.length > 0 ? entityTypes : null,
      });
      notifySuccess(`"${values.name}" saved.`);
      onOpenChange(false);
    } catch (error) {
      notifyError(error, "Couldn't save this search.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save this search</DialogTitle>
          <DialogDescription>
            Save the current query and filters so you can reapply them later.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="saved-filter-name">Name</Label>
            <Input
              id="saved-filter-name"
              placeholder="Overdue expense requests"
              aria-invalid={!!form.formState.errors.name}
              aria-describedby={form.formState.errors.name ? "saved-filter-name-error" : undefined}
              {...form.register("name")}
            />
            <FormFieldError id="saved-filter-name-error" message={form.formState.errors.name?.message} />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={createSavedFilter.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createSavedFilter.isPending}>
              {createSavedFilter.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
