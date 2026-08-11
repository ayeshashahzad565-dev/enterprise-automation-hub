"use client";

import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/patterns/confirm-dialog";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PageHeader } from "@/components/patterns/page-header";
import { Caption } from "@/components/patterns/typography";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { FileQuestion, Plus, Sparkles } from "lucide-react";

import { AiInsightCard } from "@/features/ai/components/ai-insight-card";
import { useWorkflowImprovements } from "@/features/ai/hooks/use-workflow-improvements";
import { PublishConfirmDialog } from "@/features/workflow-designer/components/publish-confirm-dialog";
import { StageInspectorPanel } from "@/features/workflow-designer/components/stage-inspector-panel";
import { VersionStatusBadge } from "@/features/workflow-designer/components/version-history-panel";
import { VersionHistoryPanel } from "@/features/workflow-designer/components/version-history-panel";
import { WorkflowCanvasSkeleton } from "@/features/workflow-designer/components/workflow-canvas/workflow-canvas-skeleton";
import { WorkflowToolbar } from "@/features/workflow-designer/components/workflow-toolbar";

// @xyflow/react is the single largest dependency in the app and needs the
// DOM to measure/lay out nodes anyway — deferred to its own chunk (and out
// of SSR) rather than loaded on every visit to this route.
const WorkflowCanvas = dynamic(
  () => import("@/features/workflow-designer/components/workflow-canvas/workflow-canvas").then((m) => m.WorkflowCanvas),
  { ssr: false, loading: () => <WorkflowCanvasSkeleton /> },
);
import { useActivateWorkflowDefinition } from "@/features/workflow-designer/hooks/use-activate-workflow-definition";
import { useAutosaveDraft } from "@/features/workflow-designer/hooks/use-autosave-draft";
import { useDeleteWorkflowDraft } from "@/features/workflow-designer/hooks/use-delete-workflow-draft";
import { useDuplicateWorkflowDefinition } from "@/features/workflow-designer/hooks/use-duplicate-workflow-definition";
import { useEditorHistory } from "@/features/workflow-designer/hooks/use-editor-history";
import { useIsDesktop } from "@/features/workflow-designer/hooks/use-is-desktop";
import { useUpdateWorkflowDraft } from "@/features/workflow-designer/hooks/use-update-workflow-draft";
import { useWorkflowVersions } from "@/features/workflow-designer/hooks/use-workflow-versions";
import { notifyError, notifySuccess } from "@/lib/toast";
import { inferStatus, type StageDefinition } from "@/types/workflow-definition";
import { ROUTES } from "@/utils/constants";

export default function WorkflowDesignerPage() {
  const params = useParams<{ requestType: string; version: string }>();
  const router = useRouter();
  const requestType = decodeURIComponent(params.requestType);
  const version = Number(params.version);
  const isDesktop = useIsDesktop();

  const { data, isLoading, isError, refetch } = useWorkflowVersions(requestType);
  const improvementsQuery = useWorkflowImprovements(requestType);
  const definitions = data?.data ?? [];
  const definition = definitions.find((d) => d.version === version) ?? null;
  const activeDefinition = definitions.find((d) => d.is_active) ?? null;
  const activeVersion = activeDefinition?.version ?? null;
  const status = definition ? inferStatus(definition, activeVersion) : null;
  const isDraft = status === "draft";

  const history = useEditorHistory<StageDefinition[]>([]);
  const [selectedOrder, setSelectedOrder] = useState<number | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    if (definition) {
      history.reset(definition.definition.stages);
      setSelectedOrder(definition.definition.stages[0]?.order ?? null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestType, version, definition]);

  const updateDraft = useUpdateWorkflowDraft();
  const activate = useActivateWorkflowDefinition();
  const duplicate = useDuplicateWorkflowDefinition();
  const deleteDraft = useDeleteWorkflowDraft();

  useAutosaveDraft({
    enabled: isDraft && Boolean(definition),
    definitionId: definition?.id ?? "",
    requestType,
    stages: history.state,
    onSaved: () => undefined,
  });

  function renumber(stages: StageDefinition[]): StageDefinition[] {
    return stages.map((stage, index) => ({ ...stage, order: index + 1 }));
  }

  function handleReorder(fromOrder: number, toOrder: number) {
    const current = [...history.state].sort((a, b) => a.order - b.order);
    const fromIndex = current.findIndex((s) => s.order === fromOrder);
    const [moved] = current.splice(fromIndex, 1);
    current.splice(toOrder - 1, 0, moved);
    history.set(renumber(current));
    setSelectedOrder(toOrder);
  }

  function handleRemove(order: number) {
    const next = renumber(history.state.filter((s) => s.order !== order));
    history.set(next);
    setSelectedOrder(next[0]?.order ?? null);
  }

  function handleDuplicateStage(order: number) {
    const source = history.state.find((s) => s.order === order);
    if (!source) return;
    const sorted = [...history.state].sort((a, b) => a.order - b.order);
    const index = sorted.findIndex((s) => s.order === order);
    sorted.splice(index + 1, 0, { ...source });
    history.set(renumber(sorted));
  }

  function handleAddStage() {
    const next: StageDefinition = {
      order: history.state.length + 1,
      name: `Stage ${history.state.length + 1}`,
      assignment_strategy: "requester_manager",
      assigned_role: null,
      department: null,
      assigned_user_id: null,
      escalation_hours: 24,
    };
    history.set([...history.state, next]);
    setSelectedOrder(next.order);
  }

  function handleStageChange(updated: StageDefinition) {
    history.set(history.state.map((s) => (s.order === updated.order ? updated : s)));
  }

  async function handleSaveDraft() {
    if (!definition) return;
    try {
      await updateDraft.mutateAsync({
        id: definition.id,
        requestType,
        body: { definition: { stages: history.state } },
      });
      notifySuccess("Draft saved.");
    } catch (error) {
      notifyError(error, "Couldn't save the draft.");
    }
  }

  async function handleOpenPublish() {
    if (!definition) return;
    try {
      await updateDraft.mutateAsync({
        id: definition.id,
        requestType,
        body: { definition: { stages: history.state } },
      });
      setPublishOpen(true);
    } catch (error) {
      notifyError(error, "Couldn't save the draft before publishing.");
    }
  }

  async function handleConfirmPublish() {
    if (!definition) return;
    try {
      await activate.mutateAsync({ id: definition.id, requestType });
      notifySuccess(`Published v${definition.version}.`);
      setPublishOpen(false);
    } catch (error) {
      notifyError(error, "Couldn't publish this workflow.");
    }
  }

  async function handleConfirmDelete() {
    if (!definition) return;
    try {
      await deleteDraft.mutateAsync({ id: definition.id, requestType });
      notifySuccess(`Deleted draft v${definition.version}.`);
      setDeleteOpen(false);
      router.push(activeVersion ? ROUTES.workflow(requestType, activeVersion) : ROUTES.workflows);
    } catch (error) {
      notifyError(error, "Couldn't delete this draft.");
    }
  }

  async function handleDuplicate() {
    if (!definition) return;
    try {
      const created = await duplicate.mutateAsync({ source: definition, targetRequestType: requestType });
      notifySuccess(`Duplicated as v${created.version}.`);
      router.push(ROUTES.workflow(created.request_type, created.version));
    } catch (error) {
      notifyError(error, "Couldn't duplicate this workflow.");
    }
  }

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTyping = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA";
      if (isTyping) return;

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) history.redo();
        else history.undo();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (isDraft) void handleSaveDraft();
      } else if (event.key === "Delete" && selectedOrder !== null && isDraft) {
        handleRemove(selectedOrder);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history, isDraft, selectedOrder]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <PageHeader title="Workflow Designer" />
        <WorkflowCanvasSkeleton />
      </div>
    );
  }

  if (isError) {
    return <ErrorState message="Couldn't load this workflow." onRetry={() => refetch()} />;
  }

  if (!definition) {
    return (
      <EmptyState
        icon={FileQuestion}
        title="Version not found"
        description={`No version ${version} exists for ${requestType}.`}
        action={{ label: "Back to Workflows", onClick: () => router.push(ROUTES.workflows) }}
      />
    );
  }

  const canvas = (
    <WorkflowCanvas
      stages={history.state}
      selectedOrder={selectedOrder}
      onSelectStage={setSelectedOrder}
      onReorderStage={handleReorder}
      onRemoveStage={handleRemove}
      onDuplicateStage={handleDuplicateStage}
      readOnly={!isDraft}
    />
  );

  const selectedStage = history.state.find((s) => s.order === selectedOrder) ?? null;

  return (
    // min-h- (not h-), and min-h-[420px] on the canvas region below: with a
    // hard h-[calc(...)] here, a long AI-suggested-improvements response
    // (variable-height, above the canvas) could squeeze the canvas's own
    // flex-1/min-h-0 region down to ~0px — React Flow would then measure a
    // 0-sized container at mount and render a nonsensically zoomed/panned
    // view (its own "parent container needs a width and a height"
    // warning). min-h- lets the page grow taller than the viewport and
    // scroll instead of clipping content when that happens; the canvas's
    // own min-h floor keeps it usable even mid-squeeze.
    <div className="flex min-h-[calc(100vh-8rem)] flex-col gap-4">
      <PageHeader
        title={`${requestType} · v${definition.version}`}
        breadcrumbs={[{ label: "Workflows", href: ROUTES.workflows }, { label: `v${definition.version}` }]}
        actions={<VersionStatusBadge status={status ?? "draft"} />}
      />

      <WorkflowToolbar
        isDraft={isDraft}
        isSaving={updateDraft.isPending}
        isDeleting={deleteDraft.isPending}
        canUndo={history.canUndo}
        canRedo={history.canRedo}
        onUndo={history.undo}
        onRedo={history.redo}
        onSaveDraft={handleSaveDraft}
        onPublish={handleOpenPublish}
        onDuplicate={handleDuplicate}
        onDelete={() => setDeleteOpen(true)}
      />

      {isDraft && (
        <Caption>
          <Button variant="link" className="h-auto p-0 text-xs" onClick={handleAddStage}>
            <Plus className="mr-1 size-3" /> Add stage
          </Button>{" "}
          · drag a stage left/right to reorder it · right-click a stage for more actions
        </Caption>
      )}

      <AiInsightCard
        title="AI-suggested improvements"
        icon={Sparkles}
        data={improvementsQuery.data}
        isLoading={improvementsQuery.isLoading}
        isError={improvementsQuery.isError}
        onRetry={() => improvementsQuery.refetch()}
      />

      {/* flex flex-col on this wrapper (not just min-h-[420px] flex-1) is required:
          ResizablePanelGroup sizes itself with `height: 100%`, and a plain block
          child's percentage height doesn't reliably resolve against an ancestor
          whose own height comes from flex-grow + min-height rather than an
          explicit `height` (verified empirically — the ancestor measured a real
          420px via getBoundingClientRect, but the percentage-height child still
          collapsed to ~3px). Making this div a flex container and the group
          `flex-1 min-h-0` sizes it via flex-grow instead, which resolves
          correctly through nested flex trees. */}
      <div className="flex min-h-[420px] flex-1 flex-col">
        <ResizablePanelGroup
          orientation={isDesktop ? "horizontal" : "vertical"}
          className="min-h-0 flex-1 rounded-lg border"
        >
          <ResizablePanel defaultSize={isDesktop ? 70 : 60} minSize={30}>
            {canvas}
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={isDesktop ? 30 : 40} minSize={20}>
            <ScrollArea className="h-full">
              <StageInspectorPanel stage={selectedStage} onChange={handleStageChange} readOnly={!isDraft} />
            </ScrollArea>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      <VersionHistoryPanel
        definitions={definitions}
        selectedVersion={version}
        onSelectVersion={(v) => router.push(ROUTES.workflow(requestType, v))}
      />

      <PublishConfirmDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        candidateStages={history.state}
        activeStages={activeDefinition?.definition.stages ?? null}
        isPublishing={activate.isPending}
        onConfirm={handleConfirmPublish}
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete this draft?"
        description={`This permanently deletes v${definition.version} of ${requestType}. This can't be undone.`}
        confirmLabel="Delete"
        isConfirming={deleteDraft.isPending}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}
