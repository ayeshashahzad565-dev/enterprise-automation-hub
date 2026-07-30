import { z } from "zod";

export const userEditSchema = z.object({
  role: z.enum(["employee", "approver", "admin"]),
  department: z.string().optional(),
});

export type UserEditFormValues = z.infer<typeof userEditSchema>;
