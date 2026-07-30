import type { VariantProps } from "class-variance-authority";
import { Archive, Check, Clock, Eye, RotateCw, X, type LucideIcon } from "lucide-react";

import { Badge, type badgeVariants } from "@/components/ui/badge";
import type { InvitationStatus } from "@/types/admin";
import type { JobStatus } from "@/types/jobs";
import type { RequestStatus } from "@/types/request";
import type { StageStatus } from "@/types/workflow";

/**
 * The one place Request/Stage status maps to a color, label, and icon —
 * every future module reuses this instead of re-deriving its own status
 * presentation. Color is never the only signal: every badge pairs its
 * color with both a text label and an icon (WCAG AA). Renders through the
 * shared `ui/badge.tsx` `Badge` component's `status-*` variants, so there
 * is exactly one badge visual language in the app, not a second parallel
 * implementation.
 */

export type DisplayRequestStatus = RequestStatus | "withdrawn";

type StatusVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

interface StatusMeta {
  label: string;
  icon: LucideIcon;
  variant: StatusVariant;
}

const REQUEST_STATUS_META: Record<DisplayRequestStatus, StatusMeta> = {
  pending: { label: "Pending", icon: Clock, variant: "status-pending" },
  in_review: { label: "In review", icon: Eye, variant: "status-in-review" },
  approved: { label: "Approved", icon: Check, variant: "status-completed" },
  completed: { label: "Completed", icon: Check, variant: "status-completed" },
  rejected: { label: "Rejected", icon: X, variant: "status-rejected" },
  withdrawn: { label: "Withdrawn", icon: Archive, variant: "status-withdrawn" },
};

const STAGE_STATUS_META: Record<StageStatus, StatusMeta> = {
  pending: REQUEST_STATUS_META.pending,
  approved: REQUEST_STATUS_META.completed,
  rejected: REQUEST_STATUS_META.rejected,
  skipped: { label: "Skipped", icon: Archive, variant: "status-withdrawn" },
};

const INVITATION_STATUS_META: Record<InvitationStatus, StatusMeta> = {
  pending: REQUEST_STATUS_META.pending,
  accepted: REQUEST_STATUS_META.completed,
  revoked: REQUEST_STATUS_META.rejected,
  expired: { label: "Expired", icon: Archive, variant: "status-withdrawn" },
};

/** `queued` and `retrying` deliberately share the `status-pending` color —
 * this design system's five status colors are reused across every module
 * rather than growing a new variant per module (see this file's own
 * header comment); the icon and label are what distinguish them, not
 * color alone. */
const JOB_STATUS_META: Record<JobStatus, StatusMeta> = {
  queued: { label: "Queued", icon: Clock, variant: "status-pending" },
  running: { label: "Running", icon: Eye, variant: "status-in-review" },
  retrying: { label: "Retrying", icon: RotateCw, variant: "status-pending" },
  succeeded: { label: "Succeeded", icon: Check, variant: "status-completed" },
  dead_lettered: { label: "Dead-lettered", icon: X, variant: "status-rejected" },
};

function StatusMetaBadge({ meta, className }: { meta: StatusMeta; className?: string }) {
  const Icon = meta.icon;
  return (
    <Badge variant={meta.variant} className={className}>
      <Icon aria-hidden />
      {meta.label}
    </Badge>
  );
}

export function StatusBadge({
  status,
  className,
}: {
  status: DisplayRequestStatus;
  className?: string;
}) {
  return <StatusMetaBadge meta={REQUEST_STATUS_META[status]} className={className} />;
}

export function StageStatusBadge({ status, className }: { status: StageStatus; className?: string }) {
  return <StatusMetaBadge meta={STAGE_STATUS_META[status]} className={className} />;
}

export function InvitationStatusBadge({
  status,
  className,
}: {
  status: InvitationStatus;
  className?: string;
}) {
  return <StatusMetaBadge meta={INVITATION_STATUS_META[status]} className={className} />;
}

export function JobStatusBadge({ status, className }: { status: JobStatus; className?: string }) {
  return <StatusMetaBadge meta={JOB_STATUS_META[status]} className={className} />;
}
