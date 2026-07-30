import { Check } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { RolePermissions } from "@/types/admin";

/** Read-only role x permission grid. See
 * `app.auth.permissions.ROLE_PERMISSIONS` — this reflects exactly what
 * the backend already enforces; no permission is invented here. */
export function PermissionMatrix({ roles }: { roles: RolePermissions[] }) {
  const allPermissions = Array.from(new Set(roles.flatMap((role) => role.permissions))).sort();

  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Permission</TableHead>
            {roles.map((role) => (
              <TableHead key={role.role} className="text-center capitalize">
                {role.role}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {allPermissions.map((permission) => (
            <TableRow key={permission}>
              <TableCell className="font-mono text-xs">{permission}</TableCell>
              {roles.map((role) => (
                <TableCell key={role.role} className="text-center">
                  {role.permissions.includes(permission) && (
                    <Check className="mx-auto size-4 text-primary" aria-label="Granted" />
                  )}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
