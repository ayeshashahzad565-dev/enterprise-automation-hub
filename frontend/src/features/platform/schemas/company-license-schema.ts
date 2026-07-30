import { z } from "zod";

/** `seat_limit` is free-typed as a string in the form (empty = unlimited)
 * and converted to `number | null` at submit time — matches
 * `expires_at`'s own optional/nullable shape on the wire. */
export const companyLicenseSchema = z.object({
  plan_tier: z
    .string()
    .trim()
    .min(1, "Plan tier is required.")
    .max(100, "Plan tier must be 100 characters or fewer."),
  seat_limit: z
    .string()
    .trim()
    .refine((value) => value === "" || (Number.isInteger(Number(value)) && Number(value) > 0), {
      message: "Seat limit must be a positive whole number, or blank for unlimited.",
    })
    .optional(),
  expires_at: z.string().trim().optional(),
  notes: z.string().trim().optional(),
});

export type CompanyLicenseFormValues = z.infer<typeof companyLicenseSchema>;
