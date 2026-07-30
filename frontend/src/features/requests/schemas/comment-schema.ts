import { z } from "zod";

export const addCommentSchema = z.object({
  body: z.string().min(1, "Comment can't be empty").max(5000, "Comment is too long"),
});

export type AddCommentFormValues = z.infer<typeof addCommentSchema>;
