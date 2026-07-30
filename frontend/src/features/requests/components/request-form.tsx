"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { FormFieldError } from "@/components/patterns/form-field-error";
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
import { Textarea } from "@/components/ui/textarea";
import { REQUEST_TYPES } from "@/features/requests/constants";
import {
  createRequestSchema,
  type CreateRequestFormValues,
} from "@/features/requests/schemas/request-schema";

export function RequestForm({
  mode,
  defaultValues,
  onSubmit,
  onCancel,
  isSubmitting,
  onValuesChange,
}: {
  mode: "create" | "edit";
  defaultValues?: Partial<CreateRequestFormValues>;
  onSubmit: (values: CreateRequestFormValues) => void | Promise<void>;
  onCancel?: () => void;
  isSubmitting?: boolean;
  onValuesChange?: (values: CreateRequestFormValues) => void;
}) {
  const form = useForm<CreateRequestFormValues>({
    resolver: zodResolver(createRequestSchema),
    defaultValues: {
      request_type: defaultValues?.request_type ?? "",
      title: defaultValues?.title ?? "",
      description: defaultValues?.description ?? "",
      department: defaultValues?.department ?? "",
    },
  });

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = form;

  useEffect(() => {
    if (!onValuesChange) return;
    const subscription = watch((values) => onValuesChange(values as CreateRequestFormValues));
    return () => subscription.unsubscribe();
  }, [watch, onValuesChange]);

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
      {mode === "create" && (
        <div className="space-y-2">
          <Label htmlFor="request_type">Request type</Label>
          <Select
            value={watch("request_type")}
            onValueChange={(value) =>
              setValue("request_type", value ?? "", { shouldValidate: true })
            }
          >
            <SelectTrigger
              id="request_type"
              className="w-full"
              aria-invalid={!!errors.request_type}
              aria-describedby={errors.request_type ? "request_type-error" : undefined}
            >
              <SelectValue placeholder="Select a request type" />
            </SelectTrigger>
            <SelectContent>
              {REQUEST_TYPES.map((type) => (
                <SelectItem key={type.value} value={type.value}>
                  {type.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FormFieldError id="request_type-error" message={errors.request_type?.message} />
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="title">Title</Label>
        <Input
          id="title"
          aria-invalid={!!errors.title}
          aria-describedby={errors.title ? "title-error" : undefined}
          {...register("title")}
        />
        <FormFieldError id="title-error" message={errors.title?.message} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          rows={4}
          aria-invalid={!!errors.description}
          aria-describedby={errors.description ? "description-error" : undefined}
          {...register("description")}
        />
        <FormFieldError id="description-error" message={errors.description?.message} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="department">Department</Label>
        <Input id="department" {...register("department")} />
      </div>

      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Saving..." : mode === "create" ? "Create request" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
