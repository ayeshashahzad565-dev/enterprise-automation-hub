import { format, isToday, isYesterday } from "date-fns";
import type { ReactNode } from "react";

import { Caption } from "@/components/patterns/typography";

function dayLabel(date: Date): string {
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";
  return format(date, "PPP");
}

/**
 * Groups a list of timestamped items into "Today" / "Yesterday" / date
 * headers — the timeline convention Activity and Notifications previously
 * lacked entirely (both rendered as a flat list, indistinguishable from
 * any other list in the app despite conceptually being a timeline).
 * Items are expected to already be sorted newest-first, matching every
 * feed this renders (the backend always returns audit/notification rows
 * ordered `created_at desc`).
 */
export function DayGroupedList<T>({
  items,
  getDate,
  getKey,
  renderItem,
}: {
  items: T[];
  getDate: (item: T) => string;
  getKey: (item: T) => string;
  renderItem: (item: T) => ReactNode;
}) {
  const groups: { label: string; items: T[] }[] = [];
  for (const item of items) {
    const label = dayLabel(new Date(getDate(item)));
    const lastGroup = groups[groups.length - 1];
    if (lastGroup?.label === label) {
      lastGroup.items.push(item);
    } else {
      groups.push({ label, items: [item] });
    }
  }

  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <div key={group.label}>
          <Caption className="px-2 pb-1">{group.label}</Caption>
          <div className="space-y-1">
            {group.items.map((item) => (
              <div key={getKey(item)}>{renderItem(item)}</div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
