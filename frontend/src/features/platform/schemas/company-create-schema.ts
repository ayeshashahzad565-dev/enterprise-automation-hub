import { z } from "zod";

/** Bounds mirror `app.api.schemas.platform.CreateCompanyBody` exactly (200). */
export const companyCreateSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Company name is required.")
    .max(200, "Company name must be 200 characters or fewer."),
});

export type CompanyCreateFormValues = z.infer<typeof companyCreateSchema>;
