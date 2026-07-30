"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { FormFieldError } from "@/components/patterns/form-field-error";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  addCommentSchema,
  type AddCommentFormValues,
} from "@/features/requests/schemas/comment-schema";

export function CommentForm({
  onSubmit,
  isSubmitting,
}: {
  onSubmit: (values: AddCommentFormValues) => void;
  isSubmitting?: boolean;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AddCommentFormValues>({
    resolver: zodResolver(addCommentSchema),
    defaultValues: { body: "" },
  });

  function submit(values: AddCommentFormValues) {
    onSubmit(values);
    reset();
  }

  return (
    <form onSubmit={handleSubmit(submit)} className="space-y-2">
      <Textarea
        id="comment-body"
        placeholder="Write a comment..."
        rows={3}
        aria-invalid={!!errors.body}
        aria-describedby={errors.body ? "comment-body-error" : undefined}
        {...register("body")}
      />
      <FormFieldError id="comment-body-error" message={errors.body?.message} />
      <div className="flex justify-end">
        <Button type="submit" size="sm" disabled={isSubmitting}>
          {isSubmitting ? "Sending..." : "Send"}
        </Button>
      </div>
    </form>
  );
}
