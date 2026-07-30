"use client";

import { Upload } from "lucide-react";
import { useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from "react";

import { cn } from "@/lib/utils";

/** Native HTML5 drag-and-drop file zone, with a file-picker fallback. No new dependency. */
export function Dropzone({
  onFileSelected,
  accept,
  disabled,
  className,
}: {
  onFileSelected: (file: File) => void;
  accept?: string;
  disabled?: boolean;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    if (disabled) return;
    const file = event.dataTransfer.files?.[0];
    if (file) onFileSelected(file);
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onFileSelected(file);
    event.target.value = "";
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!disabled && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      inputRef.current?.click();
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-disabled={disabled}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={handleKeyDown}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center transition-colors motion-reduce:transition-none",
        isDragging ? "border-primary bg-accent" : "border-border",
        disabled && "pointer-events-none cursor-not-allowed opacity-50",
        className,
      )}
    >
      <Upload className="size-6 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">Drag and drop a file, or click to browse</p>
      <p className="text-xs text-muted-foreground">Max 25 MB</p>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="sr-only"
        onChange={handleInputChange}
        disabled={disabled}
      />
    </div>
  );
}
