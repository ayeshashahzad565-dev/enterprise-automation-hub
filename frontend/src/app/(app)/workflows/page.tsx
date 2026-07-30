"use client";

import { GitBranch, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/patterns/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { DefinitionListToolbar } from "@/features/workflow-designer/components/definition-list-toolbar";
import { VersionStatusBadge } from "@/features/workflow-designer/components/version-history-panel";
import { useCreateWorkflowDefinition } from "@/features/workflow-designer/hooks/use-create-workflow-definition";
import { useWorkflowSearch } from "@/features/workflow-designer/hooks/use-workflow-search";
import { useWorkflowVersions } from "@/features/workflow-designer/hooks/use-workflow-versions";
import { inferStatus, type WorkflowDefinition } from "@/types/workflow-definition";
import { notifyError } from "@/lib/toast";
import { ROUTES } from "@/utils/constants";

export default function WorkflowsPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [activeRequestType, setActiveRequestType] = useState<string | null>(null);
  const [newWorkflowOpen, setNewWorkflowOpen] = useState(false);
  const [newRequestType, setNewRequestType] = useState("");
  const createMutation = useCreateWorkflowDefinition();

  const searchQuery = useWorkflowSearch(search);
  const versionsQuery = useWorkflowVersions(activeRequestType ?? "", {
    enabled: Boolean(activeRequestType) && !search,
  });

  const isSearching = search.trim().length > 0;
  const results = isSearching ? searchQuery : versionsQuery;
  const groupedByType = new Map<string, WorkflowDefinition[]>();
  if (results.data) {
    for (const definition of results.data.data) {
      const list = groupedByType.get(definition.request_type) ?? [];
      list.push(definition);
      groupedByType.set(definition.request_type, list);
    }
  }

  async function handleCreateWorkflow() {
    const requestType = newRequestType.trim();
    if (!requestType) return;
    try {
      const created = await createMutation.mutateAsync({
        request_type: requestType,
        definition: {
          stages: [
            {
              order: 1,
              name: "Stage 1",
              assignment_strategy: "requester_manager",
              assigned_role: null,
              department: null,
              assigned_user_id: null,
              escalation_hours: 24,
            },
          ],
        },
      });
      setNewWorkflowOpen(false);
      setNewRequestType("");
      router.push(ROUTES.workflow(created.request_type, created.version));
    } catch (error) {
      notifyError(error, "Couldn't create the workflow.");
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Workflows"
        actions={
          <Button size="sm" onClick={() => setNewWorkflowOpen(true)}>
            <Plus className="size-4" /> New workflow
          </Button>
        }
      />

      <DefinitionListToolbar
        search={search}
        onSearchChange={(value) => {
          setSearch(value);
        }}
        onQuickFilter={(requestType) => {
          setSearch("");
          setActiveRequestType(requestType);
        }}
      />

      {results.isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : results.isError ? (
        <ErrorState message="Couldn't load workflows." onRetry={() => results.refetch()} />
      ) : !activeRequestType && !isSearching ? (
        <EmptyState
          icon={GitBranch}
          title="Search or pick a request type"
          description="There's no single endpoint listing every workflow across every request type — search by name or use a quick filter chip above."
          action={{ label: "New workflow", onClick: () => setNewWorkflowOpen(true) }}
        />
      ) : groupedByType.size === 0 ? (
        <EmptyState icon={GitBranch} title="No workflows found" description="Try a different search term." />
      ) : (
        <Accordion>
          {Array.from(groupedByType.entries()).map(([requestType, definitions]) => {
            const activeVersion = definitions.find((d) => d.is_active)?.version ?? null;
            return (
              <AccordionItem key={requestType} value={requestType}>
                <AccordionTrigger>
                  {requestType} — {definitions.length} version{definitions.length === 1 ? "" : "s"}
                </AccordionTrigger>
                <AccordionContent>
                  <ul className="space-y-1">
                    {[...definitions]
                      .sort((a, b) => b.version - a.version)
                      .map((definition) => (
                        <li key={definition.id}>
                          <Button
                            variant="ghost"
                            className="h-auto w-full justify-between px-2 py-1.5"
                            onClick={() => router.push(ROUTES.workflow(requestType, definition.version))}
                          >
                            <span>v{definition.version}</span>
                            <VersionStatusBadge status={inferStatus(definition, activeVersion)} />
                          </Button>
                        </li>
                      ))}
                  </ul>
                </AccordionContent>
              </AccordionItem>
            );
          })}
        </Accordion>
      )}

      <Dialog open={newWorkflowOpen} onOpenChange={setNewWorkflowOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New workflow</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="new-request-type">Request type</Label>
            <Input
              id="new-request-type"
              value={newRequestType}
              onChange={(event) => setNewRequestType(event.target.value)}
              placeholder="e.g. expense_reimbursement"
            />
            <p className="text-xs text-muted-foreground">
              Request type is just a string — creating a workflow here does not automatically add it to
              the Create Request page&apos;s type dropdown; that&apos;s a separate, manually maintained
              list.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewWorkflowOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!newRequestType.trim() || createMutation.isPending}
              onClick={handleCreateWorkflow}
            >
              {createMutation.isPending ? "Creating…" : "Create draft"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
