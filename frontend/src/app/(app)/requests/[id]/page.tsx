"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { CheckSquare, Sparkles } from "lucide-react";
import Link from "next/link";

import { Breadcrumbs } from "@/components/patterns/breadcrumbs";
import { ConfirmDialog } from "@/components/patterns/confirm-dialog";
import { ErrorState } from "@/components/patterns/error-state";
import { SectionHeading } from "@/components/patterns/typography";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApprovalEligibility } from "@/features/approvals/hooks/use-approval-eligibility";
import { AiInsightCard } from "@/features/ai/components/ai-insight-card";
import { useRequestSummary } from "@/features/ai/hooks/use-request-summary";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import { ActivityTimeline } from "@/features/requests/components/activity-timeline";
import { AttachmentList } from "@/features/requests/components/attachment-list";
import { AttachmentUploadPanel } from "@/features/requests/components/attachment-upload-panel";
import { CommentForm } from "@/features/requests/components/comment-form";
import { CommentThread } from "@/features/requests/components/comment-thread";
import { RequestDetailHeader } from "@/features/requests/components/request-detail-header";
import { RequestForm } from "@/features/requests/components/request-form";
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
import type { CreateRequestFormValues } from "@/features/requests/schemas/request-schema";
import { useUpdateRequest } from "@/features/requests/hooks/use-update-request";
import { useUploadAttachment } from "@/features/requests/hooks/use-upload-attachment";
import { useWithdrawRequest } from "@/features/requests/hooks/use-withdraw-request";
import { useWorkflowProgress } from "@/features/requests/hooks/use-workflow-progress";
import { notifyError, notifySuccess } from "@/lib/toast";
import { useAuth } from "@/providers/auth-provider";
import { attachmentService } from "@/services/attachment-service";
import type { Attachment } from "@/types/attachment";
import { ROUTES } from "@/utils/constants";

function DetailSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

export default function RequestDetailPage() {
  const params = useParams<{ id: string }>();
  const requestId = params.id;
  const searchParams = useSearchParams();

  const { user } = useAuth();
  const { data: profile } = useCurrentUser();

  const requestQuery = useRequest(requestId);
  const summaryQuery = useRequestSummary(requestId);
  const eligibilityQuery = useApprovalEligibility(requestId);
  const workflowQuery = useWorkflowProgress(requestId);
  const auditQuery = useAuditTrail(requestId);
  const commentsQuery = useComments(requestId);
  const attachmentsQuery = useAttachments(requestId);

  const updateRequest = useUpdateRequest(requestId);
  const withdrawRequest = useWithdrawRequest();
  const addComment = useAddComment(requestId);
  const removeComment = useRemoveComment(requestId);
  const uploadAttachment = useUploadAttachment(requestId);
  const replaceAttachment = useReplaceAttachment(requestId);
  const removeAttachment = useRemoveAttachment(requestId);

  const [isEditing, setIsEditing] = useState(false);
  const [withdrawOpen, setWithdrawOpen] = useState(false);

  useEffect(() => {
    if (searchParams.get("edit") === "1") setIsEditing(true);
  }, [searchParams]);

  if (requestQuery.isLoading) {
    return <DetailSkeleton />;
  }
  if (requestQuery.isError || !requestQuery.data) {
    return (
      <ErrorState message="Couldn't load this request." onRetry={() => requestQuery.refetch()} />
    );
  }

  const request = requestQuery.data;
  const isWithdrawn = Boolean(request.deleted_at);
  const isOwner = request.requester_id === user?.id;
  const canEdit = !isWithdrawn && request.status === "pending" && isOwner;
  const canWithdraw =
    !isWithdrawn && (profile?.role === "admin" || (request.status === "pending" && isOwner));

  function canManageAttachment(attachment: Attachment): boolean {
    if (isWithdrawn) return false;
    if (profile?.role === "admin") return true;
    return attachment.uploaded_by === user?.id && request.status === "pending";
  }

  async function handleUpdate(values: CreateRequestFormValues) {
    try {
      await updateRequest.mutateAsync({
        title: values.title,
        description: values.description || undefined,
        department: values.department || undefined,
        expected_version: request.version,
      });
      notifySuccess("Request updated.");
      setIsEditing(false);
    } catch (error) {
      notifyError(error, "Couldn't save changes.");
    }
  }

  async function handleWithdraw() {
    try {
      await withdrawRequest.mutateAsync({ id: request.id, expectedVersion: request.version });
      notifySuccess("Request withdrawn.");
    } catch (error) {
      notifyError(error, "Couldn't withdraw this request.");
    } finally {
      setWithdrawOpen(false);
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
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <div className="space-y-2">
          <Breadcrumbs items={[{ label: "Requests", href: ROUTES.requests }, { label: request.title }]} />

          {isEditing ? (
            <Card>
              <CardHeader>
                <SectionHeading>Edit request</SectionHeading>
              </CardHeader>
              <CardContent>
                <RequestForm
                  mode="edit"
                  defaultValues={{
                    title: request.title,
                    description: request.description ?? "",
                    department: request.department ?? "",
                  }}
                  onSubmit={handleUpdate}
                  onCancel={() => setIsEditing(false)}
                  isSubmitting={updateRequest.isPending}
                />
              </CardContent>
            </Card>
          ) : (
            <RequestDetailHeader
              request={request}
              canEdit={canEdit}
              canWithdraw={canWithdraw}
              onEdit={() => setIsEditing(true)}
              onWithdraw={() => setWithdrawOpen(true)}
            />
          )}
        </div>

        {eligibilityQuery.data?.eligible && eligibilityQuery.data.stage_id && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-status-in-review/40 px-3 py-2 text-sm text-status-in-review-foreground">
            <span className="flex items-center gap-2">
              <CheckSquare className="size-4" /> This request is awaiting your decision.
            </span>
            <Button
              size="sm"
              variant="outline"
              render={<Link href={ROUTES.approval(eligibilityQuery.data.stage_id)} />}
            >
              Review
            </Button>
          </div>
        )}

        <AiInsightCard
          title="AI summary"
          icon={Sparkles}
          data={summaryQuery.data}
          isLoading={summaryQuery.isLoading}
          isError={summaryQuery.isError}
          onRetry={() => summaryQuery.refetch()}
        />

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

        <Tabs defaultValue="comments">
          <TabsList>
            <TabsTrigger value="comments">Comments</TabsTrigger>
            <TabsTrigger value="attachments">Attachments</TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
          </TabsList>
          <TabsContent value="comments" className="space-y-4">
            {commentsQuery.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : commentsQuery.isError ? (
              <ErrorState message="Couldn't load comments." onRetry={() => commentsQuery.refetch()} />
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
            ) : attachmentsQuery.isError ? (
              <ErrorState
                message="Couldn't load attachments."
                onRetry={() => attachmentsQuery.refetch()}
              />
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
            ) : auditQuery.isError ? (
              <ErrorState message="Couldn't load activity." onRetry={() => auditQuery.refetch()} />
            ) : (
              <ActivityTimeline entries={auditQuery.data ?? []} />
            )}
          </TabsContent>
        </Tabs>
      </div>

      <div className="space-y-4">
        <RequestMetadataPanel request={request} />
      </div>

      <ConfirmDialog
        open={withdrawOpen}
        onOpenChange={setWithdrawOpen}
        title="Withdraw this request?"
        description="This can't be undone."
        confirmLabel="Withdraw"
        isConfirming={withdrawRequest.isPending}
        onConfirm={handleWithdraw}
      />
    </div>
  );
}
