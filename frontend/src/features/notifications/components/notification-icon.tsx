import { AlertTriangle, Bell, CheckCircle2, Info, PartyPopper, UserPlus } from "lucide-react";

import type { NotificationType } from "@/types/notification";

const ICONS: Record<NotificationType, typeof Bell> = {
  assignment: UserPlus,
  reminder: Bell,
  escalation: AlertTriangle,
  decision: CheckCircle2,
  completion: PartyPopper,
  system: Info,
};

export function NotificationIcon({
  type,
  className,
}: {
  type: NotificationType;
  className?: string;
}) {
  const Icon = ICONS[type];
  return <Icon className={className} aria-hidden />;
}
