import { FileQuestion } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { ROUTES } from "@/utils/constants";

export default function NotFound() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
      <FileQuestion className="size-8 text-muted-foreground" aria-hidden />
      <p className="text-display font-semibold tracking-tight">404</p>
      <p className="max-w-md text-sm text-muted-foreground">
        The page you&apos;re looking for doesn&apos;t exist.
      </p>
      <Button render={<Link href={ROUTES.dashboard} />}>Back to dashboard</Button>
    </div>
  );
}
