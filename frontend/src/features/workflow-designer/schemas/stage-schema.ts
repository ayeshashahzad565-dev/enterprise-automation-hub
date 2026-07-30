import { z } from "zod";

/**
 * Mirrors the backend's real, enforced structural rules exactly (per the
 * Phase 6 audit of `app.models.workflow.StageDefinition`): name non-empty,
 * escalation_hours > 0, and each assignment strategy's required field
 * present. This lets the inspector reject an invalid stage before a
 * server round-trip, without inventing any rule the backend doesn't
 * itself enforce.
 */
export const stageSchema = z
  .object({
    order: z.number().int().positive(),
    name: z.string().min(1, "Stage name is required"),
    assignment_strategy: z.enum(["specific_user", "department_queue", "requester_manager"]),
    assigned_role: z.enum(["employee", "approver", "admin"]).nullable(),
    department: z.string().nullable(),
    assigned_user_id: z.string().nullable(),
    escalation_hours: z.number().positive("Must be greater than 0"),
  })
  .superRefine((stage, ctx) => {
    if (stage.assignment_strategy === "specific_user" && !stage.assigned_user_id) {
      ctx.addIssue({
        code: "custom",
        path: ["assigned_user_id"],
        message: "Required for the Specific user strategy",
      });
    }
    if (stage.assignment_strategy === "department_queue") {
      if (!stage.department) {
        ctx.addIssue({ code: "custom", path: ["department"], message: "Required for Department queue" });
      }
      if (!stage.assigned_role) {
        ctx.addIssue({ code: "custom", path: ["assigned_role"], message: "Required for Department queue" });
      }
    }
  });

export type StageFormValues = z.infer<typeof stageSchema>;
