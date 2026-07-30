"use client";

import { Sparkles } from "lucide-react";

import { SectionHeading } from "@/components/patterns/typography";
import { ErrorState } from "@/components/patterns/error-state";
import { StatusBadge } from "@/components/patterns/status-badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApprovalActionBar } from "@/features/approvals/components/approval-action-bar";
import { useApprovalEligibility } from "@/features/approvals/hooks/use-approval-eligibility";
import { useApproveStage } from "@/features/approvals/hooks/use-approve-stage";
import { useRejectStage } from "@/features/approvals/hooks/use-reject-stage";
import { AiInsightCard } from "@/features/ai/components/ai-insight-card";
import { useApprovalSummary } from "@/features/ai/hooks/use-approval-summary";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import { ActivityTimeline } from "@/features/requests/components/activity-timeline";
import { AttachmentList } from "@/features/requests/components/attachment-list";
import { AttachmentUploadPanel } from "@/features/requests/components/attachment-upload-panel";
import { CommentForm } from "@/features/requests/components/comment-form";
import { CommentThread } from "@/features/requests/components/comment-thread";
import { RequestMetadataPanel } from "@/features/requests/components/request-metadata-panel";
import { WorkflowProgressStepper } from "@/features/requests/components/workflow-progress-stepper";
import { useAddComment } from "@/features/requests/hooks/use-add-comment";
import { useAttachments } from "@/features/requests/hooks/use-attachments";
import { useAuditTrail } from "@/features/requests/hooks/use-audit-trail";
import { useComments } from "@/features/requests/hooks/use-comments";
import { useRemoveAttachment } from "@/features/requests/hooks/use-remove-attachment";
import { useRemoveComment } from "@/features/requests/hooks/use-remove-comment";
import { useReplaceAttachment } from "@/features/requests/hooks/use-replace-attachment";
import { useRequest } from "@/features/requests/hooks/use-request";
import { useUploadAttachment } from "@/features/requests/hooks/use-upload-attachment";
import { useWorkflowProgress } from "@/features/requests/hooks/use-workflow-progress";
import { notifyError, notifySuccess } from "@/lib/toast";
import { useAuth } from "@/providers/auth-provider";
import { attachmentService } from "@/services/attachment-service";
import type { Attachment } from "@/types/attachment";

/**
 * The Approval Detail view — composes Phase 2's existing Requests
 * components (metadata, workflow stepper, comments, attachments, audit
 * trail) rather than reimplementing them, and adds the one genuinely new
 * piece: `ApprovalActionBar`. Renders identically inside the full-page
 * route, the split-view right pane, and the side-preview sheet.
 */
export function ApprovalDetailContent({
  requestId,
  stageId: knownStageId,
  stageVersion: knownStageVersion,
  onDecided,
}: {
  requestId: string;
  stageId?: string;
  stageVersion?: number;
  onDecided?: () => void;
}) {
  const { user } = useAuth();
  const { data: profile } = useCurrentUser();
  const isAdmin = profile?.role === "admin";

  const requestQuery = useRequest(requestId);
  const summaryQuery = useApprovalSummary(requestId);
  const workflowQuery = useWorkflowProgress(requestId);
  const auditQuery = useAuditTrail(requestId);
  const commentsQuery = useComments(requestId);
  const attachmentsQuery = useAttachments(requestId);
  const eligibilityQuery = useApprovalEligibility(requestId, {
    enabled: knownStageId === undefined,
  });

  const addComment = useAddComment(requestId);
  const removeComment = useRemoveComment(requestId);
  const uploadAttachment = useUploadAttachment(requestId);
  const replaceAttachment = useReplaceAttachment(requestId);
  const removeAttachment = useRemoveAttachment(requestId);
  const approveStage = useApproveStage();
  const rejectStage = useRejectStage();

  if (requestQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (requestQuery.isError || !requestQuery.data) {
    return (
      <ErrorState message="Couldn't load this request." onRetry={() => requestQuery.refetch()} />
    );
  }

  const request = requestQuery.data;
  const isWithdrawn = Boolean(request.deleted_at);

  const stageId = knownStageId ?? eligibilityQuery.data?.stage_id ?? undefined;
  const stageVersion = knownStageVersion ?? eligibilityQuery.data?.expected_version ?? undefined;
  const canDecide = Boolean(stageId && stageVersion && !isWithdrawn);

  function canManageAttachment(attachment: Attachment): boolean {
    if (isWithdrawn) return false;
    if (isAdmin) return true;
    return attachment.uploaded_by === user?.id && request.status === "pending";
  }

  async function handleApprove(note: string | undefined) {
    if (!stageId || !stageVersion) return;
    try {
      await approveStage.mutateAsync({
        stageId,
        input: { expected_version: stageVersion, decision_note: note },
      });
      notifySuccess("Request approved.");
      onDecided?.();
    } catch (error) {
      notifyError(error, "Couldn't approve this request.");
    }
  }

  async function handleReject(note: string) {
    if (!stageId || !stageVersion) return;
    try {
      await rejectStage.mutateAsync({
        stageId,
        input: { expected_version: stageVersion, decision_note: note },
      });
      notifySuccess("Request rejected.");
      onDecided?.();
    } catch (error) {
      notifyError(error, "Couldn't reject this request.");
    }
  }

  async function handleAddComment(values: { body: string }) {
    try {
      await addComment.mutateAsync({ body: values.body });
    } catch (error) {
      notifyError(error, "Couldn't post this comment.");
    }
  }

  async function handleUploadAttachment(file: File) {
    try {
      await uploadAttachment.mutateAsync(file);
      notifySuccess("File uploaded.");
    } catch (error) {
      notifyError(error, "Couldn't upload this file.");
    }
  }

  async function handleDownload(attachment: Attachment) {
    try {
      const { url } = await attachmentService.getDownloadUrl(attachment.id);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (error) {
      notifyError(error, "Couldn't get a download link.");
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-6 overflow-auto p-1">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <SectionHeading>{request.title}</SectionHeading>
            <StatusBadge status={isWithdrawn ? "withdrawn" : request.status} />
          </div>
          {request.description && (
            <p className="text-sm text-muted-foreground">{request.description}</p>
          )}
        </div>

        <Card>
          <CardHeader>
            <SectionHeading>Workflow</SectionHeading>
          </CardHeader>
          <CardContent>
            {workflowQuery.isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : workflowQuery.data ? (
              <WorkflowProgressStepper progress={workflowQuery.data} />
            ) : (
              <ErrorState
                message="Couldn't load workflow progress."
                onRetry={() => workflowQuery.refetch()}
              />
            )}
          </CardContent>
        </Card>

        <AiInsightCard
          title="AI summary for approvers"
          icon={Sparkles}
          data={summaryQuery.data}
          isLoading={summaryQuery.isLoading}
          isError={summaryQuery.isError}
          onRetry={() => summaryQuery.refetch()}
        />

        <RequestMetadataPanel request={request} />

        <Tabs defaultValue="comments">
          <TabsList>
            <TabsTrigger value="comments">Comments</TabsTrigger>
            <TabsTrigger value="attachments">Attachments</TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
          </TabsList>
          <TabsContent value="comments" className="space-y-4">
            {commentsQuery.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <>
                <CommentThread
                  comments={commentsQuery.data?.data ?? []}
                  onRemove={(id) => removeComment.mutate(id)}
                />
                {!isWithdrawn && (
                  <CommentForm onSubmit={handleAddComment} isSubmitting={addComment.isPending} />
                )}
              </>
            )}
          </TabsContent>
          <TabsContent value="attachments" className="space-y-4">
            {attachmentsQuery.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <>
                <AttachmentList
                  attachments={attachmentsQuery.data?.data ?? []}
                  canManage={canManageAttachment}
                  onDownload={handleDownload}
                  onReplace={(attachment, file) =>
                    replaceAttachment.mutate(
                      { attachmentId: attachment.id, file },
                      {
                        onSuccess: () => notifySuccess("File replaced."),
                        onError: (error) => notifyError(error, "Couldn't replace this file."),
                      },
                    )
                  }
                  onRemove={(attachment) =>
                    removeAttachment.mutate(attachment.id, {
                      onSuccess: () => notifySuccess("Attachment removed."),
                      onError: (error) => notifyError(error, "Couldn't remove this attachment."),
                    })
                  }
                />
                {!isWithdrawn && (
                  <AttachmentUploadPanel
                    onFileSelected={handleUploadAttachment}
                    disabled={uploadAttachment.isPending}
                  />
                )}
              </>
            )}
          </TabsContent>
          <TabsContent value="activity">
            {auditQuery.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <ActivityTimeline entries={auditQuery.data ?? []} />
            )}
          </TabsContent>
        </Tabs>
      </div>

      {canDecide && (
        <ApprovalActionBar
          isSubmitting={approveStage.isPending || rejectStage.isPending}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}
    </div>
  );
}
