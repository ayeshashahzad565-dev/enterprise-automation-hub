import { z } from "zod";

/** Bounds mirror `app.api.schemas.search.CreateSavedFilterBody` exactly (100). */
export const saveFilterSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "A name is required.")
    .max(100, "Name must be 100 characters or fewer."),
});

export type SaveFilterFormValues = z.infer<typeof saveFilterSchema>;
