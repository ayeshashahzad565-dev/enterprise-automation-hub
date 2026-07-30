import Link from "next/link";

import { getSearchEntityMeta } from "@/features/search/components/search-result-icon";
import { renderHighlightedSnippet } from "@/features/search/lib/render-highlighted-snippet";
import { getSearchResultHref } from "@/features/search/lib/result-href";
import { cn } from "@/lib/utils";
import type { SearchResult } from "@/types/search";

const ENTITY_ORDER: SearchResult["entity_type"][] = [
  "request",
  "approval",
  "workflow",
  "comment",
  "attachment",
  "notification",
  "audit_entry",
  "user",
  "department",
];

export function groupByEntityType(results: SearchResult[]): [SearchResult["entity_type"], SearchResult[]][] {
  const groups = new Map<SearchResult["entity_type"], SearchResult[]>();
  for (const result of results) {
    const bucket = groups.get(result.entity_type);
    if (bucket) {
      bucket.push(result);
    } else {
      groups.set(result.entity_type, [result]);
    }
  }
  return ENTITY_ORDER.filter((type) => groups.has(type)).map((type) => [type, groups.get(type)!]);
}

function SearchResultRow({
  result,
  active,
  onMouseEnter,
}: {
  result: SearchResult;
  active: boolean;
  onMouseEnter: () => void;
}) {
  const href = getSearchResultHref(result);
  const content = (
    <div
      className={cn(
        "flex flex-col gap-0.5 rounded-lg px-3 py-2",
        active && "bg-muted",
        href && "cursor-pointer",
      )}
      onMouseEnter={onMouseEnter}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium">{result.title}</span>
        <span className="shrink-0 text-xs text-muted-foreground">{result.subtitle}</span>
      </div>
      {result.snippet && (
        <p className="truncate text-xs text-muted-foreground">
          {renderHighlightedSnippet(result.snippet)}
        </p>
      )}
    </div>
  );
  return href ? (
    <Link href={href} data-result-id={result.id}>
      {content}
    </Link>
  ) : (
    <div data-result-id={result.id}>{content}</div>
  );
}

export function SearchResultList({
  results,
  activeId,
  onHover,
}: {
  results: SearchResult[];
  activeId?: string | null;
  onHover?: (id: string) => void;
}) {
  const groups = groupByEntityType(results);

  return (
    <div className="space-y-4">
      {groups.map(([entityType, items]) => {
        const { label } = getSearchEntityMeta(entityType);
        return (
          <div key={entityType} className="space-y-1">
            <p className="px-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {label}
            </p>
            <div className="space-y-0.5">
              {items.map((result) => (
                <SearchResultRow
                  key={result.id}
                  result={result}
                  active={activeId === result.id}
                  onMouseEnter={() => onHover?.(result.id)}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
