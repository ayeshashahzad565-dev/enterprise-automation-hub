"use client";

import { Caption, SectionHeading } from "@/components/patterns/typography";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { QueueStats } from "@/types/jobs";

const INACTIVE_COPY = "Inactive — Redis isn't configured on this backend instance.";

/** `queue_depth`/`delayed_count` are `null` (not empty) when this backend
 * instance has no Redis configured — rendered here as an explicit
 * "inactive" state rather than a zero, which would misleadingly read as
 * "queues are empty." `dead_letter_count` is never null. */
export function QueueStatsPanel({ stats }: { stats: QueueStats }) {
  const deadLetterEntries = Object.entries(stats.dead_letter_count);
  const delayedEntries = stats.delayed_count ? Object.entries(stats.delayed_count) : null;

  return (
    <div className="grid gap-3 md:grid-cols-3">
      <Card size="sm">
        <CardContent className="space-y-2">
          <SectionHeading className="text-sm">Queue depth</SectionHeading>
          {stats.queue_depth === null ? (
            <Caption>{INACTIVE_COPY}</Caption>
          ) : stats.queue_depth.length === 0 ? (
            <Caption>All queues empty.</Caption>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Queue</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead className="text-right">Depth</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {stats.queue_depth.map((entry) => (
                  <TableRow key={`${entry.queue_name}-${entry.priority}`}>
                    <TableCell>{entry.queue_name}</TableCell>
                    <TableCell className="capitalize">{entry.priority}</TableCell>
                    <TableCell className="text-right tabular-nums">{entry.depth}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardContent className="space-y-2">
          <SectionHeading className="text-sm">Delayed (scheduled for later)</SectionHeading>
          {delayedEntries === null ? (
            <Caption>{INACTIVE_COPY}</Caption>
          ) : delayedEntries.length === 0 ? (
            <Caption>Nothing delayed.</Caption>
          ) : (
            <ul className="space-y-1 text-sm">
              {delayedEntries.map(([queue, count]) => (
                <li key={queue} className="flex items-center justify-between">
                  <span className="text-muted-foreground">{queue}</span>
                  <span className="font-medium tabular-nums">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardContent className="space-y-2">
          <SectionHeading className="text-sm">Dead-lettered</SectionHeading>
          {deadLetterEntries.length === 0 ? (
            <Caption>None.</Caption>
          ) : (
            <ul className="space-y-1 text-sm">
              {deadLetterEntries.map(([queue, count]) => (
                <li key={queue} className="flex items-center justify-between">
                  <span className="text-muted-foreground">{queue}</span>
                  <span className={count > 0 ? "font-medium text-destructive tabular-nums" : "font-medium tabular-nums"}>
                    {count}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
