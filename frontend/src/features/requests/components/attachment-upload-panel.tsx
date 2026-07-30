"use client";

import { Dropzone } from "@/components/patterns/dropzone";

const ACCEPTED_TYPES =
  ".pdf,.png,.jpg,.jpeg,.gif,.txt,.csv,.doc,.docx,.xls,.xlsx,.zip";

export function AttachmentUploadPanel({
  onFileSelected,
  disabled,
}: {
  onFileSelected: (file: File) => void;
  disabled?: boolean;
}) {
  return <Dropzone onFileSelected={onFileSelected} accept={ACCEPTED_TYPES} disabled={disabled} />;
}
