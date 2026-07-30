"use client";

import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { FeatureFlag } from "@/types/platform";

/** Simple, non-`DataTable` table — matches `NotificationPreferencesList`'s
 * shape, not the `@tanstack/react-table`-backed pattern used for
 * paginated resources, since this list is short, unpaginated (the backend
 * returns a plain array), and every row is just a toggle. */
export function FeatureFlagsTable({
  flags,
  pendingKey,
  onToggle,
}: {
  flags: FeatureFlag[];
  pendingKey: string | null;
  onToggle: (key: string, enabled: boolean) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Key</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Enabled</TableHead>
            <TableHead>Last updated</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {flags.map((flag) => (
            <TableRow key={flag.key}>
              <TableCell className="font-mono text-xs">{flag.key}</TableCell>
              <TableCell className="text-sm text-muted-foreground">{flag.description}</TableCell>
              <TableCell>
                <Switch
                  checked={flag.enabled}
                  disabled={pendingKey === flag.key}
                  onCheckedChange={(checked) => onToggle(flag.key, checked)}
                  aria-label={`${flag.enabled ? "Disable" : "Enable"} ${flag.key}`}
                />
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {new Date(flag.updated_at).toLocaleString()}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
