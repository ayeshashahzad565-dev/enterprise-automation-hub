import { z } from "zod";

/** Bounds mirror `app.api.schemas.platform.FeatureFlagCreateBody` exactly (100/unbounded). */
export const featureFlagCreateSchema = z.object({
  key: z
    .string()
    .trim()
    .min(1, "Key is required.")
    .max(100, "Key must be 100 characters or fewer.")
    .regex(/^[a-z0-9_]+$/, "Use lowercase letters, numbers, and underscores only."),
  description: z.string().trim().min(1, "Description is required."),
  enabled: z.boolean(),
});

export type FeatureFlagCreateFormValues = z.infer<typeof featureFlagCreateSchema>;
