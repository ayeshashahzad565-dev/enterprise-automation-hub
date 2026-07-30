/**
 * Frontend-owned types for the REST envelope documented in
 * `docs/api_design.md` §9/§11 of the backend repository. These are defined
 * independently of any backend Python class — they describe the wire
 * contract, not a mirror of a server-side model.
 */

export interface ApiMeta {
  timestamp: string;
  request_id: string;
}

export interface ApiSuccessBody<T> {
  data: T;
  meta: ApiMeta;
}

export interface PaginationMeta {
  page: number;
  page_size: number;
  total_records: number;
  total_pages: number;
}

export interface ApiListBody<T> {
  data: T[];
  pagination: PaginationMeta;
  meta: ApiMeta;
}

export interface ApiErrorDetail {
  field?: string;
  message?: string;
  [key: string]: unknown;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: ApiErrorDetail[];
  };
  meta: ApiMeta;
}
