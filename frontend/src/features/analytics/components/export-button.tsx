"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { notifyError } from "@/lib/toast";
import { analyticsService } from "@/services/analytics-service";

export function ExportButton({
  endpoint,
  filters,
  filename,
}: {
  endpoint: string;
  filters: object;
  filename: string;
}) {
  const [isExporting, setIsExporting] = useState(false);

  async function handleExport() {
    setIsExporting(true);
    try {
      await analyticsService.exportCsv(endpoint, filters, filename);
    } catch (error) {
      notifyError(error, "Couldn't export this report.");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <Button variant="outline" size="sm" disabled={isExporting} onClick={handleExport}>
      <Download className="size-4" /> {isExporting ? "Exporting…" : "Export CSV"}
    </Button>
  );
}
