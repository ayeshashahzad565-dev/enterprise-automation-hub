"use client";

import { formatDistanceToNow } from "date-fns";
import { Download, FileText, RefreshCw, Trash2 } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import type { Attachment } from "@/types/attachment";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function AttachmentRow({
  attachment,
  canManage,
  onDownload,
  onReplace,
  onRemove,
}: {
  attachment: Attachment;
  canManage: boolean;
  onDownload: () => void;
  onReplace: (file: File) => void;
  onRemove: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <li className="flex items-center justify-between gap-2 rounded-lg border p-3">
      <div className="flex min-w-0 items-center gap-2">
        <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{attachment.file_name}</p>
          <p className="text-xs text-muted-foreground">
            {formatBytes(attachment.size_bytes)} ·{" "}
            {formatDistanceToNow(new Date(attachment.created_at), { addSuffix: true })}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button variant="ghost" size="icon" aria-label="Download" onClick={onDownload}>
          <Download className="size-4" />
        </Button>
        {canManage && (
          <>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Replace file"
              onClick={() => inputRef.current?.click()}
            >
              <RefreshCw className="size-4" />
            </Button>
            <input
              ref={inputRef}
              type="file"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onReplace(file);
                event.target.value = "";
              }}
            />
            <Button variant="ghost" size="icon" aria-label="Remove attachment" onClick={onRemove}>
              <Trash2 className="size-4" />
            </Button>
          </>
        )}
      </div>
    </li>
  );
}

export function AttachmentList({
  attachments,
  canManage,
  onDownload,
  onReplace,
  onRemove,
}: {
  attachments: Attachment[];
  canManage: (attachment: Attachment) => boolean;
  onDownload: (attachment: Attachment) => void;
  onReplace: (attachment: Attachment, file: File) => void;
  onRemove: (attachment: Attachment) => void;
}) {
  if (attachments.length === 0) {
    return <p className="text-sm text-muted-foreground">No attachments yet.</p>;
  }

  return (
    <ul className="space-y-2">
      {attachments.map((attachment) => (
        <AttachmentRow
          key={attachment.id}
          attachment={attachment}
          canManage={canManage(attachment)}
          onDownload={() => onDownload(attachment)}
          onReplace={(file) => onReplace(attachment, file)}
          onRemove={() => onRemove(attachment)}
        />
      ))}
    </ul>
  );
}
