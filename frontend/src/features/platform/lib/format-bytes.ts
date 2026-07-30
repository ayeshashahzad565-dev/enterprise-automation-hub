/** Human-readable byte size for platform-wide attachment storage totals
 * — extends `attachment-list.tsx`'s local KB/MB-only `formatBytes` with
 * GB/TB tiers, since a platform-wide total can exceed what any single
 * attachment would ever reach. */
export function formatStorageBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}
