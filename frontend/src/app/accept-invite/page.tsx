import { Suspense } from "react";

import { AcceptInviteContent } from "@/features/invitation-acceptance/components/accept-invite-content";
import { AcceptInviteSkeleton } from "@/features/invitation-acceptance/components/accept-invite-skeleton";
import { WorkflowNetwork } from "@/features/auth/components/workflow-network";

/**
 * Public, unauthenticated route — the first screen a newly invited
 * employee ever sees. Deliberately mirrors `/login`'s split-panel shell
 * markup exactly (same brand panel, same `WorkflowNetwork` hero, same
 * right-column width/spacing) rather than introducing a second visual
 * language for this milestone, per the approved architecture's explicit
 * instruction to keep this page "native to the rest of the product."
 * `/login`'s own layout is not extracted into a shared component here —
 * duplicating this small, static shell keeps this milestone's change
 * confined to files the Invitation Acceptance feature actually owns,
 * rather than touching the existing login page to share it.
 */
export default function AcceptInvitePage() {
  return (
    <div className="flex flex-1">
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-[#08090d] p-12 text-slate-100 md:flex">
        <WorkflowNetwork className="pointer-events-none absolute inset-0 size-full" />

        <div className="relative flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-md bg-white/10 text-sm font-bold backdrop-blur-sm">
            A
          </span>
          <span className="text-lg font-bold tracking-tight">Automata</span>
        </div>

        <div className="relative space-y-3">
          <div className="inline-flex items-center gap-1.5 rounded-full bg-white/8 px-3 py-1 text-xs font-medium text-slate-300 backdrop-blur-sm">
            You&apos;ve been invited
          </div>
          <p className="text-display font-bold tracking-tight">Join your team on Automata.</p>
          <p className="max-w-md text-sm text-slate-400">
            Set a password to activate your account and start collaborating on requests,
            approvals, and workflows.
          </p>
        </div>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <Suspense fallback={<AcceptInviteSkeleton />}>
            <AcceptInviteContent />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
