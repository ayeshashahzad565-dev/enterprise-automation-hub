import { z } from "zod";

/** Backs the company detail page's settings form — `name` isn't
 * editable here (renamed via the same field the create dialog uses, but
 * this form is scoped to contact/notes only, matching the milestone's
 * "settings form (contact_email, notes)" scope). */
export const companySettingsSchema = z.object({
  contact_email: z
    .string()
    .trim()
    .max(254, "Email must be 254 characters or fewer.")
    .email("Enter a valid email address.")
    .optional()
    .or(z.literal("")),
  notes: z.string().trim().optional(),
});

export type CompanySettingsFormValues = z.infer<typeof companySettingsSchema>;
