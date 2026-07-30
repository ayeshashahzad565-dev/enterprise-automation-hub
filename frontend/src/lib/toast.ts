import { toast } from "sonner";

import { ApiError } from "@/lib/api/errors";

export function notifySuccess(message: string): void {
  toast.success(message);
}

export function notifyError(error: unknown, fallback: string): void {
  toast.error(error instanceof ApiError ? error.message : fallback);
}
