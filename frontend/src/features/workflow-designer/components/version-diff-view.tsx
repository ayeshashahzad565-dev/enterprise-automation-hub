import { cn } from "@/lib/utils";
import { diffStages } from "@/features/workflow-designer/lib/diff-stages";
import type { StageDefinition } from "@/types/workflow-definition";

const KIND_STYLES: Record<string, string> = {
  added: "border-status-completed bg-status-completed/10",
  removed: "border-status-rejected bg-status-rejected/10",
  changed: "border-status-in-review bg-status-in-review/10",
  unchanged: "border-border",
};

const KIND_LABELS: Record<string, string> = {
  added: "Added",
  removed: "Removed",
  changed: "Changed",
  unchanged: "Unchanged",
};

/** Stage-by-stage diff between two definition versions, computed client-side from already-fetched documents. */
export function VersionDiffView({
  before,
  after,
}: {
  before: StageDefinition[];
  after: StageDefinition[];
}) {
  const rows = diffStages(before, after);

  return (
    <ol className="space-y-2">
      {rows.map((row) => (
        <li
          key={row.order}
          className={cn("rounded-md border px-3 py-2 text-sm", KIND_STYLES[row.kind])}
        >
          <div className="flex items-center justify-between">
            <span className="font-medium">
              Stage {row.order}: {(row.after ?? row.before)?.name}
            </span>
            <span className="text-xs text-muted-foreground">{KIND_LABELS[row.kind]}</span>
          </div>
          {row.kind === "changed" && row.before && row.after && (
            <p className="mt-1 text-xs text-muted-foreground">
              {row.before.name !== row.after.name && `Name: "${row.before.name}" → "${row.after.name}". `}
              {row.before.escalation_hours !== row.after.escalation_hours &&
                `Escalation: ${row.before.escalation_hours}h → ${row.after.escalation_hours}h. `}
              {row.before.assignment_strategy !== row.after.assignment_strategy &&
                `Assignment: ${row.before.assignment_strategy} → ${row.after.assignment_strategy}.`}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
