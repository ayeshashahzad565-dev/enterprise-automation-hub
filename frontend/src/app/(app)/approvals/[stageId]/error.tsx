"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/patterns/error-state";

export default function ApprovalDetailError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return <ErrorState message="Something went wrong loading this approval." onRetry={reset} />;
}
