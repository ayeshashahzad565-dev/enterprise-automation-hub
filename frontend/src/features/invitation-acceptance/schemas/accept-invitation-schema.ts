import { z } from "zod";

/**
 * The backend's `InvitationAcceptBody.password` enforces only
 * non-empty + a defensive 4096-char upper bound (see
 * `app.api.schemas.public_invitations`'s own docstring: password policy
 * is Supabase Auth's concern, not this codebase's). No frontend password
 * field anywhere in this app enforces a length floor either (the login
 * form only requires non-empty — signing in with an already-chosen
 * password has nothing to validate).
 *
 * This form is different: it is where a password is *chosen* for the
 * first time, and Supabase Auth's own platform-level minimum (6
 * characters, unless reconfigured) would otherwise reject a too-short
 * value *after* submission, surfacing as this page's generic
 * infrastructure-failure state rather than a clear inline message. An
 * 8-character floor here is a conservative, deliberately simple
 * (length-only, no character-class rules) client-side guard against that
 * — not a stricter policy than the backend enforces, just an earlier,
 * clearer checkpoint before the value ever reaches it.
 */
const MIN_PASSWORD_LENGTH = 8;

export const acceptInvitationSchema = z
  .object({
    password: z
      .string()
      .min(MIN_PASSWORD_LENGTH, `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`),
    confirmPassword: z.string().min(1, "Please confirm your password."),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  });

export type AcceptInvitationFormValues = z.infer<typeof acceptInvitationSchema>;
