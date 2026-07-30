import type { StageDefinition } from "@/types/workflow-definition";

export type StageDiffKind = "added" | "removed" | "changed" | "unchanged";

export interface StageDiffRow {
  kind: StageDiffKind;
  order: number;
  before: StageDefinition | null;
  after: StageDefinition | null;
}

/**
 * A stage-by-stage diff between two definition versions, purely
 * client-side presentation logic over already-fetched documents (no new
 * backend computation). Stages are matched by `order` — the only
 * structural identity the backend model has (there's no stable per-stage
 * id) — so a diff row represents "whatever occupies this position in the
 * chain," honestly, not a fuzzy content-based match.
 */
export function diffStages(before: StageDefinition[], after: StageDefinition[]): StageDiffRow[] {
  const maxOrder = Math.max(before.length, after.length);
  const rows: StageDiffRow[] = [];
  for (let order = 1; order <= maxOrder; order += 1) {
    const beforeStage = before.find((s) => s.order === order) ?? null;
    const afterStage = after.find((s) => s.order === order) ?? null;
    if (beforeStage && !afterStage) {
      rows.push({ kind: "removed", order, before: beforeStage, after: null });
    } else if (!beforeStage && afterStage) {
      rows.push({ kind: "added", order, before: null, after: afterStage });
    } else if (beforeStage && afterStage) {
      const changed = JSON.stringify(beforeStage) !== JSON.stringify(afterStage);
      rows.push({ kind: changed ? "changed" : "unchanged", order, before: beforeStage, after: afterStage });
    }
  }
  return rows;
}

export function summarizeDiff(rows: StageDiffRow[]): { added: number; removed: number; changed: number } {
  return {
    added: rows.filter((r) => r.kind === "added").length,
    removed: rows.filter((r) => r.kind === "removed").length,
    changed: rows.filter((r) => r.kind === "changed").length,
  };
}
