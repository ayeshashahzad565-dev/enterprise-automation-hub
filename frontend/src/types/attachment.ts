export type AttachmentScanStatus = "skipped" | "clean" | "infected" | "scan_error";

export interface Attachment {
  id: string;
  request_id: string;
  uploaded_by: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  storage_path: string;
  checksum_sha256: string;
  version: number;
  replaces_attachment_id: string | null;
  scan_status: AttachmentScanStatus;
  deleted_at: string | null;
  deleted_by: string | null;
  created_at: string;
}
