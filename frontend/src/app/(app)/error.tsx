"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect } from "react";

import { SectionHeading } from "@/components/patterns/typography";
import { Button } from "@/components/ui/button";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
      <AlertTriangle className="size-8 text-muted-foreground" aria-hidden />
      <SectionHeading>Couldn&apos;t load this page</SectionHeading>
      <p className="max-w-md text-sm text-muted-foreground">{error.message}</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
