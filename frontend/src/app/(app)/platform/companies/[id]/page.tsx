"use client";

import { useParams } from "next/navigation";
import Link from "next/link";

import { Breadcrumbs } from "@/components/patterns/breadcrumbs";
import { ErrorState } from "@/components/patterns/error-state";
import { PageTitle, SectionHeading } from "@/components/patterns/typography";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CompanyLicensePanel } from "@/features/platform/components/company-license-panel";
import { CompanySettingsForm } from "@/features/platform/components/company-settings-form";
import { CompanyStatusBadge } from "@/features/platform/components/company-status-badge";
import { PlatformActivityList } from "@/features/platform/components/platform-activity-list";
import { useCompany } from "@/features/platform/hooks/use-company";
import { useCompanyLicense } from "@/features/platform/hooks/use-company-license";
import { usePlatformAuditLog } from "@/features/platform/hooks/use-platform-audit-log";
import { ROUTES } from "@/utils/constants";

export default function PlatformCompanyDetailPage() {
  const params = useParams<{ id: string }>();
  const companyId = params.id;

  const companyQuery = useCompany(companyId);
  const licenseQuery = useCompanyLicense(companyId);
  const activityQuery = usePlatformAuditLog({ company_id: companyId, page_size: 10 });

  const company = companyQuery.data;

  return (
    <div className="space-y-4">
      <Breadcrumbs
        items={[
          { label: "Platform", href: ROUTES.platform },
          { label: "Companies", href: ROUTES.platformCompanies },
          { label: company?.name ?? "Company" },
        ]}
      />

      {companyQuery.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : companyQuery.isError || !company ? (
        <ErrorState message="Couldn't load this company." onRetry={() => companyQuery.refetch()} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <PageTitle>{company.name}</PageTitle>
            <CompanyStatusBadge company={company} />
            <span className="font-mono text-xs text-muted-foreground">{company.slug}</span>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card size="sm">
              <CardContent className="space-y-3">
                <SectionHeading>Settings</SectionHeading>
                <CompanySettingsForm company={company} />
              </CardContent>
            </Card>

            <Card size="sm">
              <CardContent className="space-y-3">
                <SectionHeading>License</SectionHeading>
                {licenseQuery.isLoading ? (
                  <Skeleton className="h-48 w-full" />
                ) : licenseQuery.isError ? (
                  <ErrorState message="Couldn't load the license." onRetry={() => licenseQuery.refetch()} />
                ) : (
                  <CompanyLicensePanel companyId={company.id} license={licenseQuery.data ?? null} />
                )}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <SectionHeading>Recent activity</SectionHeading>
              <Link
                href={`${ROUTES.platformAudit}?company_id=${company.id}`}
                className="text-sm text-primary hover:underline"
              >
                View full history
              </Link>
            </div>
            {activityQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : activityQuery.isError ? (
              <ErrorState message="Couldn't load recent activity." onRetry={() => activityQuery.refetch()} />
            ) : (activityQuery.data?.data.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground">No recorded activity for this company yet.</p>
            ) : (
              <Card size="sm">
                <CardContent>
                  <PlatformActivityList entries={activityQuery.data?.data ?? []} />
                </CardContent>
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}
