import { PageTitle } from "@/components/patterns/typography";
import { LoginForm } from "@/features/auth/components/login-form";
import { WorkflowNetwork } from "@/features/auth/components/workflow-network";

export default function LoginPage() {
  return (
    <div className="flex flex-1">
      {/* A deliberately dark, near-black panel (independent of the app's own
          light/dark toggle) — the workflow network's restrained indigo glow
          reads as premium against real darkness; the previous solid
          --primary (bright indigo) fill left the "dark charcoal nodes, soft
          indigo glow" contrast nowhere to actually show up. */}
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
            Enterprise automation, orchestrated
          </div>
          <p className="text-display font-bold tracking-tight">
            Approvals, workflows, and analytics — in one place.
          </p>
          <p className="max-w-md text-sm text-slate-400">
            A single system of record for requests, approvals, and the workflows that route them.
          </p>
        </div>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center p-6">
        <div className="w-full max-w-sm space-y-6">
          <div className="space-y-1.5 text-center md:text-left">
            <PageTitle>Sign in</PageTitle>
            <p className="text-sm text-muted-foreground">
              Welcome back to Automata.
            </p>
          </div>
          <LoginForm />
        </div>
      </div>
    </div>
  );
}
