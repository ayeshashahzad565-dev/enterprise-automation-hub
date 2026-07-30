import type { ReactNode } from "react";

/**
 * Renders a `SearchResult.snippet` (Markdown with the match `**bolded**`,
 * per `app.services.search_service._highlight_snippet`) as `<mark>`
 * spans rather than literal asterisks.
 */
export function renderHighlightedSnippet(snippet: string): ReactNode {
  const parts = snippet.split(/(\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <mark key={index} className="rounded-sm bg-primary/20 px-0.5 text-foreground">
        {part.slice(2, -2)}
      </mark>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}
