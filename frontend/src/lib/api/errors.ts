import type { ApiErrorDetail } from "@/lib/api/types";

export interface ApiErrorParams {
  code: string;
  message: string;
  status: number;
  details?: ApiErrorDetail[];
  requestId?: string;
}

/** A typed error thrown by `apiClient` for every non-2xx response. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: ApiErrorDetail[];
  readonly requestId?: string;

  constructor({ code, message, status, details, requestId }: ApiErrorParams) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }
}
