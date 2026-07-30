import { DefinitionList, DefinitionRow } from "@/components/patterns/definition-list";
import { Caption, SectionHeading } from "@/components/patterns/typography";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { PlatformSettings } from "@/types/admin";

/** Read-only — `AppSettings` is loaded once from environment variables at
 * process startup with no persisted, runtime-mutable settings table, so
 * there is nothing here to edit. SMTP credentials and connection strings
 * are never sent by the backend in the first place — see
 * `app.api.schemas.admin.PlatformSettingsOut`'s docstring. */
export function PlatformSettingsView({ settings }: { settings: PlatformSettings }) {
  return (
    <div className="space-y-4">
      <Card size="sm">
        <CardContent className="space-y-1">
          <div className="flex items-center justify-between">
            <SectionHeading>Platform metadata</SectionHeading>
            <Badge variant="secondary" className="capitalize">
              {settings.environment}
            </Badge>
          </div>
          <Caption>Read-only — no backend write path exists for these values.</Caption>
        </CardContent>
      </Card>

      <Card size="sm">
        <CardContent>
          <SectionHeading className="mb-2">Default workflow behavior</SectionHeading>
          <DefinitionList>
            <DefinitionRow label="Default escalation window">
              {settings.default_escalation_hours} hours
            </DefinitionRow>
          </DefinitionList>
        </CardContent>
      </Card>

      <Card size="sm">
        <CardContent>
          <SectionHeading className="mb-2">Notification defaults</SectionHeading>
          <DefinitionList>
            <DefinitionRow label="Email dispatch (SMTP)">
              {settings.smtp_enabled ? "Enabled" : "Disabled"}
            </DefinitionRow>
            <DefinitionRow label="Notification poll rate">
              {settings.notification_poll_per_minute} / min
            </DefinitionRow>
          </DefinitionList>
        </CardContent>
      </Card>

      <Card size="sm">
        <CardContent>
          <SectionHeading className="mb-2">Security settings</SectionHeading>
          <DefinitionList>
            <DefinitionRow label="Read requests">{settings.read_per_minute} / min</DefinitionRow>
            <DefinitionRow label="Write requests">{settings.write_per_minute} / min</DefinitionRow>
            <DefinitionRow label="Uploads">{settings.upload_per_minute} / min</DefinitionRow>
            <DefinitionRow label="Login attempts">{settings.login_per_5_minutes} / 5 min</DefinitionRow>
            <DefinitionRow label="Log level">{settings.log_level}</DefinitionRow>
          </DefinitionList>
        </CardContent>
      </Card>
    </div>
  );
}
