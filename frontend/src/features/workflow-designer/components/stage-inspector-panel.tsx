"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { EmptyState } from "@/components/patterns/empty-state";
import { FormFieldError } from "@/components/patterns/form-field-error";
import { SectionHeading } from "@/components/patterns/typography";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { stageSchema, type StageFormValues } from "@/features/workflow-designer/schemas/stage-schema";
import type { StageDefinition } from "@/types/workflow-definition";
import { MousePointerClick } from "lucide-react";

const STRATEGY_OPTIONS: ReadonlyArray<{ value: StageFormValues["assignment_strategy"]; label: string }> = [
  { value: "specific_user", label: "Specific user" },
  { value: "department_queue", label: "Department queue" },
  { value: "requester_manager", label: "Requester's manager" },
];

const ROLE_OPTIONS: ReadonlyArray<{ value: NonNullable<StageFormValues["assigned_role"]>; label: string }> = [
  { value: "employee", label: "Employee" },
  { value: "approver", label: "Approver" },
  { value: "admin", label: "Admin" },
];

/** Right-side property inspector for the selected stage node. Raw react-hook-form + zod, matching `RequestForm`'s existing convention (no shadcn `form` wrapper). */
export function StageInspectorPanel({
  stage,
  onChange,
  readOnly = false,
}: {
  stage: StageDefinition | null;
  onChange: (stage: StageDefinition) => void;
  readOnly?: boolean;
}) {
  const form = useForm<StageFormValues>({
    resolver: zodResolver(stageSchema),
    defaultValues: stage ?? undefined,
  });
  const { register, watch, setValue, formState: { errors } } = form;

  useEffect(() => {
    if (stage) form.reset(stage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage?.order]);

  useEffect(() => {
    const subscription = watch((values) => {
      const result = stageSchema.safeParse(values);
      if (result.success) onChange(result.data);
    });
    return () => subscription.unsubscribe();
  }, [watch, onChange]);

  if (!stage) {
    return (
      <EmptyState
        icon={MousePointerClick}
        title="No stage selected"
        description="Select a stage on the canvas to edit its properties."
      />
    );
  }

  const strategy = watch("assignment_strategy");

  return (
    <form className="space-y-4 p-4" noValidate>
      <SectionHeading>Stage properties</SectionHeading>

      <div className="space-y-2">
        <Label htmlFor="stage-name">Name</Label>
        <Input
          id="stage-name"
          disabled={readOnly}
          aria-invalid={!!errors.name}
          aria-describedby={errors.name ? "stage-name-error" : undefined}
          {...register("name")}
        />
        <FormFieldError id="stage-name-error" message={errors.name?.message} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="stage-strategy">Assignment</Label>
        <Select
          value={strategy ?? ""}
          onValueChange={(value) =>
            setValue("assignment_strategy", value as StageFormValues["assignment_strategy"], {
              shouldValidate: true,
            })
          }
          disabled={readOnly}
        >
          <SelectTrigger id="stage-strategy" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STRATEGY_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {strategy === "department_queue" && (
        <>
          <div className="space-y-2">
            <Label htmlFor="stage-department">Department</Label>
            <Input
              id="stage-department"
              disabled={readOnly}
              aria-invalid={!!errors.department}
              aria-describedby={errors.department ? "stage-department-error" : undefined}
              {...register("department")}
            />
            <FormFieldError id="stage-department-error" message={errors.department?.message} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="stage-role">Eligible role</Label>
            <Select
              value={watch("assigned_role") ?? undefined}
              onValueChange={(value) =>
                setValue("assigned_role", value as StageFormValues["assigned_role"], {
                  shouldValidate: true,
                })
              }
              disabled={readOnly}
            >
              <SelectTrigger
                id="stage-role"
                className="w-full"
                aria-invalid={!!errors.assigned_role}
                aria-describedby={errors.assigned_role ? "stage-role-error" : undefined}
              >
                <SelectValue placeholder="Select a role" />
              </SelectTrigger>
              <SelectContent>
                {ROLE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormFieldError id="stage-role-error" message={errors.assigned_role?.message} />
          </div>
        </>
      )}

      {strategy === "specific_user" && (
        <div className="space-y-2">
          <Label htmlFor="stage-user-id">User id</Label>
          <Input
            id="stage-user-id"
            disabled={readOnly}
            placeholder="UUID"
            aria-invalid={!!errors.assigned_user_id}
            aria-describedby={errors.assigned_user_id ? "stage-user-id-error" : undefined}
            {...register("assigned_user_id")}
          />
          <p className="text-xs text-muted-foreground">
            No user directory exists to search by name — paste the user&apos;s id directly.
          </p>
          <FormFieldError id="stage-user-id-error" message={errors.assigned_user_id?.message} />
        </div>
      )}

      {strategy === "requester_manager" && (
        <p className="text-xs text-muted-foreground">
          Resolved automatically against the requester&apos;s own department at submission time — no
          additional field needed.
        </p>
      )}

      <div className="space-y-2">
        <Label htmlFor="stage-escalation">Escalate after (hours)</Label>
        <Input
          id="stage-escalation"
          type="number"
          min={0}
          step="any"
          disabled={readOnly}
          aria-invalid={!!errors.escalation_hours}
          aria-describedby={errors.escalation_hours ? "stage-escalation-error" : undefined}
          {...register("escalation_hours", { valueAsNumber: true })}
        />
        <p className="text-xs text-muted-foreground">
          After this many hours pending, the stage escalates to an Admin — a fixed fallback, not
          configurable.
        </p>
        <FormFieldError id="stage-escalation-error" message={errors.escalation_hours?.message} />
      </div>
    </form>
  );
}
