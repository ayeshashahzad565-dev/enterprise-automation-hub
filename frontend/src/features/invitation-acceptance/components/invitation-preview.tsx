import { DefinitionList, DefinitionRow } from "@/components/patterns/definition-list";
import type { InvitationValidation } from "@/types/invitation";

/**
 * Shows exactly the fields the backend's validate response carries —
 * full name, email, role, department, expiry — and nothing else. There
 * is no id/status/resend-count/token to accidentally render here in the
 * first place; `InvitationValidation` (`@/types/invitation`) never
 * includes them, matching the backend's own minimal response shape.
 */
export function InvitationPreview({ invitation }: { invitation: InvitationValidation }) {
  return (
    <DefinitionList className="rounded-lg border px-3">
      <DefinitionRow label="Full name">{invitation.full_name}</DefinitionRow>
      <DefinitionRow label="Email">{invitation.email}</DefinitionRow>
      <DefinitionRow label="Role">
        <span className="capitalize">{invitation.role}</span>
      </DefinitionRow>
      <DefinitionRow label="Department">{invitation.department ?? "—"}</DefinitionRow>
      <DefinitionRow label="Expires">
        {new Date(invitation.expires_at).toLocaleString(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        })}
      </DefinitionRow>
    </DefinitionList>
  );
}
