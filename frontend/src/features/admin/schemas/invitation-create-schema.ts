import { z } from "zod";

/** Bounds mirror `app.api.schemas.admin_invitations.InvitationCreateBody`
 * exactly (254/200/200), so an oversized value is rejected client-side
 * with a specific message rather than surfacing the backend's generic
 * 422 as a raw error. */
export const invitationCreateSchema = z.object({
  full_name: z
    .string()
    .trim()
    .min(1, "Full name is required.")
    .max(200, "Full name must be 200 characters or fewer."),
  email: z
    .string()
    .trim()
    .min(3, "Email is required.")
    .max(254, "Email must be 254 characters or fewer.")
    .email("Enter a valid email address."),
  role: z.enum(["employee", "approver", "admin"]),
  department: z
    .string()
    .trim()
    .max(200, "Department must be 200 characters or fewer.")
    .optional(),
});

export type InvitationCreateFormValues = z.infer<typeof invitationCreateSchema>;
