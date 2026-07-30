"use client";

import { CheckCircle2, HelpCircle, XCircle, type LucideIcon } from "lucide-react";

import { Caption, SectionHeading } from "@/components/patterns/typography";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PlatformHealth } from "@/types/platform";

type DependencyState = "ok" | "unreachable" | "not_configured" | "unknown";

function badgeFor(state: DependencyState): { variant: "status-completed" | "status-rejected" | "secondary"; icon: LucideIcon; label: string } {
  switch (state) {
    case "ok":
      return { variant: "status-completed", icon: CheckCircle2, label: "OK" };
    case "unreachable":
      return { variant: "status-rejected", icon: XCircle, label: "Unreachable" };
    case "not_configured":
      return { variant: "secondary", icon: HelpCircle, label: "Not configured" };
    default:
      return { variant: "secondary", icon: HelpCircle, label: "Unknown" };
  }
}

function DependencyCard({ label, state }: { label: string; state: DependencyState }) {
  const meta = badgeFor(state);
  const Icon = meta.icon;
  return (
    <Card size="sm">
      <CardContent className="flex items-center justify-between gap-2">
        <SectionHeading className="text-sm">{label}</SectionHeading>
        <Badge variant={meta.variant}>
          <Icon /> {meta.label}
        </Badge>
      </CardContent>
    </Card>
  );
}

/** One card per dependency the backend's `/platform/health` composes —
 * `redis`/`job_queue` are only present in the response when Redis is
 * configured on the backend instance, rendered here as "Not configured"
 * rather than a false "Unreachable", the same convention
 * `QueueStatsPanel` already uses for its own Redis-optional fields. */
export function HealthStatusCards({ health }: { health: PlatformHealth }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <DependencyCard label="Database" state={health.database} />
        <DependencyCard label="Redis" state={health.redis ?? "not_configured"} />
        <DependencyCard
          label="Scheduler"
          state={health.scheduler_active ? "ok" : "unreachable"}
        />
        <DependencyCard label="Job queue" state={health.job_queue ?? "not_configured"} />
      </div>

      <div className="space-y-2">
        <SectionHeading>Dead-letter backlog</SectionHeading>
        {!health.dead_letter_by_queue ? (
          <Caption>Inactive — Redis isn&apos;t configured on this backend instance.</Caption>
        ) : Object.keys(health.dead_letter_by_queue).length === 0 ? (
          <Caption>No dead-lettered jobs on any queue.</Caption>
        ) : (
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Queue</TableHead>
                  <TableHead className="text-right">Dead-lettered</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(health.dead_letter_by_queue).map(([queue, count]) => (
                  <TableRow key={queue}>
                    <TableCell>{queue}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      <span className={count > 0 ? "font-medium text-destructive" : "font-medium"}>
                        {count}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
