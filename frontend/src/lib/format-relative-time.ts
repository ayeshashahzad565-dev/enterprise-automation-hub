import { formatDistanceToNowStrict } from "date-fns";

/** "2 hours ago" style relative timestamp — the Notification/Activity Center's first use of this style in the app (every prior feature used absolute `format(date, "PPp")` timestamps). */
export function formatRelativeTime(isoDate: string): string {
  return formatDistanceToNowStrict(new Date(isoDate), { addSuffix: true });
}
