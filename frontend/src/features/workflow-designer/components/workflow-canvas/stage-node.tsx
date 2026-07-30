"use client";

import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { AlertTriangle, Copy, Trash2, Users } from "lucide-react";

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { cn } from "@/lib/utils";
import type { StageDefinition } from "@/types/workflow-definition";

export interface StageNodeData extends Record<string, unknown> {
  stage: StageDefinition;
  isSelected: boolean;
  readOnly: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onDuplicate: () => void;
}

export type StageNodeType = Node<StageNodeData, "stage">;

const STRATEGY_LABELS: Record<StageDefinition["assignment_strategy"], string> = {
  specific_user: "Specific user",
  department_queue: "Department queue",
  requester_manager: "Requester's manager",
};

function assignmentSummary(stage: StageDefinition): string {
  if (stage.assignment_strategy === "department_queue") {
    return `${STRATEGY_LABELS.department_queue} · ${stage.department ?? "—"} · ${stage.assigned_role ?? "—"}`;
  }
  if (stage.assignment_strategy === "specific_user") {
    return `${STRATEGY_LABELS.specific_user} · ${stage.assigned_user_id?.slice(0, 8) ?? "—"}`;
  }
  return STRATEGY_LABELS.requester_manager;
}

/** Custom React Flow node rendering one workflow stage. Content is a thin presentational shell — all reordering/removal logic lives in the canvas wrapper. */
export function StageNode({ data }: NodeProps<StageNodeType>) {
  const { stage, isSelected, readOnly, onSelect, onRemove, onDuplicate } = data;

  const content = (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-48 flex-col gap-1 rounded-lg border bg-card p-3 text-left shadow-sm transition-colors",
        isSelected ? "border-primary ring-2 ring-primary/30" : "border-border hover:border-primary/50",
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-border" />
      <p className="truncate text-sm font-medium">{stage.name}</p>
      <p className="flex items-center gap-1 truncate text-xs text-muted-foreground">
        <Users className="size-3 shrink-0" aria-hidden />
        {assignmentSummary(stage)}
      </p>
      <p className="flex items-center gap-1 text-xs text-muted-foreground">
        <AlertTriangle className="size-3 shrink-0" aria-hidden />
        Escalates after {stage.escalation_hours}h
      </p>
      <Handle type="source" position={Position.Right} className="!bg-border" />
    </button>
  );

  if (readOnly) return content;

  return (
    <ContextMenu>
      <ContextMenuTrigger>{content}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onClick={onDuplicate}>
          <Copy className="mr-2 size-4" /> Duplicate stage
        </ContextMenuItem>
        <ContextMenuItem variant="destructive" onClick={onRemove}>
          <Trash2 className="mr-2 size-4" /> Remove stage
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
