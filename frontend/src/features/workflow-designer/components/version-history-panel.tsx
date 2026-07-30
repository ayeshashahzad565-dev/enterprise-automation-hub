"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { VersionDiffView } from "@/features/workflow-designer/components/version-diff-view";
import { inferStatus, type WorkflowDefinition } from "@/types/workflow-definition";

/** Draft/Active/Archived tabs (inferred from version number relative to the active version — see `inferStatus`), each version row offering a "Compare" action against the currently open version. */
export function VersionHistoryPanel({
  definitions,
  selectedVersion,
  onSelectVersion,
}: {
  definitions: WorkflowDefinition[];
  selectedVersion: number;
  onSelectVersion: (version: number) => void;
}) {
  const [compareTarget, setCompareTarget] = useState<WorkflowDefinition | null>(null);
  const activeDefinition = definitions.find((d) => d.is_active) ?? null;
  const activeVersion = activeDefinition?.version ?? null;
  const selectedDefinition = definitions.find((d) => d.version === selectedVersion) ?? null;

  const buckets = {
    active: definitions.filter((d) => inferStatus(d, activeVersion) === "active"),
    draft: definitions.filter((d) => inferStatus(d, activeVersion) === "draft"),
    archived: definitions.filter((d) => inferStatus(d, activeVersion) === "archived"),
  };

  function row(definition: WorkflowDefinition) {
    return (
      <li
        key={definition.id}
        className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
      >
        <button
          type="button"
          className="flex-1 truncate text-left"
          onClick={() => onSelectVersion(definition.version)}
        >
          v{definition.version} {definition.version === selectedVersion && "(open)"}
        </button>
        {definition.version !== selectedVersion && (
          <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => setCompareTarget(definition)}>
            Compare
          </Button>
        )}
      </li>
    );
  }

  return (
    <div className="space-y-2">
      <Tabs defaultValue="draft">
        <TabsList>
          <TabsTrigger value="draft">Draft ({buckets.draft.length})</TabsTrigger>
          <TabsTrigger value="active">Active ({buckets.active.length})</TabsTrigger>
          <TabsTrigger value="archived">
            <Tooltip>
              <TooltipTrigger>Archived ({buckets.archived.length})</TooltipTrigger>
              <TooltipContent>Inferred from version order — not a stored backend status.</TooltipContent>
            </Tooltip>
          </TabsTrigger>
        </TabsList>
        <TabsContent value="draft">
          <ul className="space-y-0.5">{buckets.draft.map(row)}</ul>
        </TabsContent>
        <TabsContent value="active">
          <ul className="space-y-0.5">{buckets.active.map(row)}</ul>
        </TabsContent>
        <TabsContent value="archived">
          <ul className="space-y-0.5">{buckets.archived.map(row)}</ul>
        </TabsContent>
      </Tabs>

      <Dialog open={compareTarget !== null} onOpenChange={(open) => !open && setCompareTarget(null)}>
        <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              v{compareTarget?.version} vs v{selectedVersion}
            </DialogTitle>
          </DialogHeader>
          {compareTarget && selectedDefinition && (
            <VersionDiffView
              before={compareTarget.definition.stages}
              after={selectedDefinition.definition.stages}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** Named distinctly from `components/patterns/status-badge.tsx`'s
 * `StatusBadge` — this one renders the Draft/Active/Archived inference
 * described in this file's own module docstring, an unrelated concept
 * from a request/stage's lifecycle status. */
export function VersionStatusBadge({ status }: { status: "active" | "draft" | "archived" }) {
  const variant = status === "active" ? "default" : status === "draft" ? "secondary" : "outline";
  const label = status === "active" ? "Active" : status === "draft" ? "Draft" : "Archived";
  return <Badge variant={variant}>{label}</Badge>;
}
