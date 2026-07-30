import { ShieldAlert } from "lucide-react";
import Link from "next/link";

import { PageTitle } from "@/components/patterns/typography";
import { Button } from "@/components/ui/button";
import { ROUTES } from "@/utils/constants";

export default function UnauthorizedPage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
      <ShieldAlert className="size-8 text-muted-foreground" aria-hidden />
      <PageTitle>You don&apos;t have access to this page</PageTitle>
      <p className="max-w-md text-sm text-muted-foreground">
        Your account doesn&apos;t have permission to view this resource. If you think this is a
        mistake, contact an administrator.
      </p>
      <Button render={<Link href={ROUTES.dashboard} />}>Back to dashboard</Button>
    </div>
  );
}
