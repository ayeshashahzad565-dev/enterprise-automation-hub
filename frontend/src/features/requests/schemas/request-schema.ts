import { z } from "zod";

export const createRequestSchema = z.object({
  request_type: z.string().min(1, "Select a request type"),
  title: z.string().min(1, "Title is required").max(200, "Title must be 200 characters or fewer"),
  description: z.string().max(5000, "Description must be 5,000 characters or fewer").optional(),
  department: z.string().optional(),
});

export type CreateRequestFormValues = z.infer<typeof createRequestSchema>;

export const patchRequestSchema = z.object({
  title: z.string().min(1, "Title is required").max(200).optional(),
  description: z.string().max(5000).optional(),
  department: z.string().optional(),
});

export type PatchRequestFormValues = z.infer<typeof patchRequestSchema>;
