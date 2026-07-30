import { CheckCircle2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { ROUTES } from "@/utils/constants";

/**
 * Deliberately does not sign the new user in or store any credential —
 * per the milestone's explicit instruction, the only affordance here is
 * a link to the existing `/login` page; the user's first sign-in is a
 * normal, explicit login, not an automatic session handoff.
 */
export function AcceptInviteSuccess({ fullName }: { fullName: string }) {
  return (
    <div className="flex flex-col items-center gap-4 text-center">
      <div className="flex size-14 items-center justify-center rounded-full bg-status-completed">
        <CheckCircle2 className="size-7 text-status-completed-foreground" aria-hidden />
      </div>
      <div className="space-y-1.5">
        <p className="text-heading font-semibold">You&apos;re all set, {fullName}</p>
        <p className="mx-auto max-w-sm text-sm text-muted-foreground">
          Your account has been created. Sign in with your new password to get started.
        </p>
      </div>
      <Button render={<Link href={ROUTES.login} />} className="w-full max-w-xs">
        Go to sign in
      </Button>
    </div>
  );
}
