import type { ReactNode } from "react";

import { Breadcrumbs, type BreadcrumbEntry } from "@/components/patterns/breadcrumbs";
import { PageTitle } from "@/components/patterns/typography";

export function PageHeader({
  breadcrumbs,
  title,
  description,
  actions,
}: {
  breadcrumbs?: BreadcrumbEntry[];
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="space-y-2">
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <PageTitle>{title}</PageTitle>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
