"use client";

import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/patterns/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { RequestForm } from "@/features/requests/components/request-form";
import { useCreateRequest } from "@/features/requests/hooks/use-create-request";
import { useRequestDraft } from "@/features/requests/hooks/use-request-draft";
import type { CreateRequestFormValues } from "@/features/requests/schemas/request-schema";
import { notifyError, notifySuccess } from "@/lib/toast";
import { ROUTES } from "@/utils/constants";

export default function NewRequestPage() {
  const router = useRouter();
  const createRequest = useCreateRequest();
  const { draft, isReady, save, clear, dismiss } = useRequestDraft();

  async function handleSubmit(values: CreateRequestFormValues) {
    try {
      const created = await createRequest.mutateAsync({
        request_type: values.request_type,
        title: values.title,
        description: values.description || undefined,
        department: values.department || undefined,
      });
      clear();
      notifySuccess("Request created.");
      router.push(ROUTES.request(created.id));
    } catch (error) {
      notifyError(error, "Couldn't create this request.");
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <PageHeader
        breadcrumbs={[{ label: "Requests", href: ROUTES.requests }, { label: "New request" }]}
        title="New request"
        description="Submit a new request for approval."
      />

      {draft && (
        <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/50 px-4 py-3 text-sm">
          <span>You have an unsaved draft from a previous visit.</span>
          <Button size="sm" variant="outline" onClick={dismiss}>
            Discard
          </Button>
        </div>
      )}

      <Card>
        <CardContent className="pt-6">
          {isReady ? (
            <RequestForm
              mode="create"
              defaultValues={draft ?? undefined}
              onSubmit={handleSubmit}
              onCancel={() => router.push(ROUTES.requests)}
              isSubmitting={createRequest.isPending}
              onValuesChange={save}
            />
          ) : (
            <div className="space-y-4">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
