"use client";

import { format } from "date-fns";

import { DefinitionList, DefinitionRow } from "@/components/patterns/definition-list";
import { SectionHeading } from "@/components/patterns/typography";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { useAuth } from "@/providers/auth-provider";
import type { Request } from "@/types/request";

export function RequestMetadataPanel({ request }: { request: Request }) {
  const { user } = useAuth();
  const isOwnRequest = user?.id === request.requester_id;

  return (
    <Card>
      <CardHeader>
        <SectionHeading>Metadata</SectionHeading>
      </CardHeader>
      <CardContent>
        <DefinitionList>
          <DefinitionRow label="Requester">
            {isOwnRequest ? "You" : `${request.requester_id.slice(0, 8)}…`}
          </DefinitionRow>
          <DefinitionRow label="Type">{request.request_type}</DefinitionRow>
          <DefinitionRow label="Department">{request.department ?? "—"}</DefinitionRow>
          <DefinitionRow label="Created">{format(new Date(request.created_at), "PPp")}</DefinitionRow>
          <DefinitionRow label="Last updated">
            {format(new Date(request.updated_at), "PPp")}
          </DefinitionRow>
          {request.completed_at && (
            <DefinitionRow label="Completed">
              {format(new Date(request.completed_at), "PPp")}
            </DefinitionRow>
          )}
          <DefinitionRow label="Version">{String(request.version)}</DefinitionRow>
        </DefinitionList>
      </CardContent>
    </Card>
  );
}
