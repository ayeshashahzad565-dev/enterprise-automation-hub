import { createClient } from "@/lib/supabase/client";
import { ApiError } from "@/lib/api/errors";
import type { ApiErrorBody, ApiListBody, ApiSuccessBody, PaginationMeta } from "@/lib/api/types";
import { API_BASE_URL, ROUTES } from "@/utils/constants";

async function buildHeaders(options?: { json?: boolean }): Promise<Record<string, string>> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const headers: Record<string, string> = {};
  if (options?.json !== false) {
    headers["Content-Type"] = "application/json";
  }
  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`;
  }
  return headers;
}

/** Signs the caller out and sends them back to /login once a session is confirmed gone. */
async function handleUnauthorized(): Promise<void> {
  const supabase = createClient();
  await supabase.auth.signOut();
  if (typeof window !== "undefined") {
    window.location.assign(ROUTES.login);
  }
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody | undefined> {
  try {
    return (await response.json()) as ApiErrorBody;
  } catch {
    return undefined;
  }
}

/**
 * A single 401 doesn't necessarily mean this session is invalid — it can
 * also mean the access token expired between page load and this request,
 * or a transient server-side hiccup got mislabeled as an auth failure.
 * Refresh the session and retry once before treating it as a real
 * sign-out; only if the refresh itself fails (or the retry also 401s) is
 * the session actually dead.
 */
async function refreshSession(): Promise<boolean> {
  const supabase = createClient();
  const { data, error } = await supabase.auth.refreshSession();
  return !error && data.session !== null;
}

async function rawRequest(
  path: string,
  init?: RequestInit,
  options?: { json?: boolean },
): Promise<Response> {
  const headers = await buildHeaders(options);
  let response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { ...headers, ...init?.headers },
  });

  if (response.status === 401) {
    const refreshed = await refreshSession();
    if (refreshed) {
      const retryHeaders = await buildHeaders(options);
      response = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers: { ...retryHeaders, ...init?.headers },
      });
    }
  }

  if (!response.ok) {
    if (response.status === 401) {
      await handleUnauthorized();
    }
    const requestIdHeader = response.headers.get("X-Request-Id") ?? undefined;
    const body = await parseErrorBody(response);
    throw new ApiError({
      code: body?.error.code ?? "INTERNAL_ERROR",
      message: body?.error.message ?? "An unexpected error occurred.",
      status: response.status,
      details: body?.error.details,
      requestId: body?.meta.request_id ?? requestIdHeader,
    });
  }

  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await rawRequest(path, init);
  if (response.status === 204) {
    return undefined as T;
  }
  const body = (await response.json()) as ApiSuccessBody<T>;
  return body.data;
}

async function requestList<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T[]; pagination: PaginationMeta }> {
  const response = await rawRequest(path, init);
  const body = (await response.json()) as ApiListBody<T>;
  return { data: body.data, pagination: body.pagination };
}

async function requestForm<T>(path: string, method: string, formData: FormData): Promise<T> {
  const response = await rawRequest(path, { method, body: formData }, { json: false });
  if (response.status === 204) {
    return undefined as T;
  }
  const body = (await response.json()) as ApiSuccessBody<T>;
  return body.data;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return { method, body: body === undefined ? undefined : JSON.stringify(body) };
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  getList: <T>(path: string) => requestList<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) => request<T>(path, jsonInit("POST", body)),
  patch: <T>(path: string, body?: unknown) => request<T>(path, jsonInit("PATCH", body)),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** Multipart form submission (file uploads) — never JSON-encoded. */
  postForm: <T>(path: string, formData: FormData) => requestForm<T>(path, "POST", formData),
  putForm: <T>(path: string, formData: FormData) => requestForm<T>(path, "PUT", formData),
  /** Raw (non-JSON) responses — e.g. a `?format=csv` export download. */
  getBlob: async (path: string): Promise<Blob> => (await rawRequest(path, { method: "GET" })).blob(),
};
