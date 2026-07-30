"use client";

import {
  Activity,
  BarChart3,
  Bell,
  CheckSquare,
  FileText,
  GitBranch,
  LayoutDashboard,
  Moon,
  Plus,
  SearchIcon,
  ShieldCheck,
  Sun,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { getSearchEntityMeta } from "@/features/search/components/search-result-icon";
import { groupByEntityType } from "@/features/search/components/search-result-list";
import { getSearchResultHref } from "@/features/search/lib/result-href";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { searchService } from "@/services/search-service";
import type { SearchResult } from "@/types/search";
import { OPEN_COMMAND_PALETTE_EVENT, ROUTES } from "@/utils/constants";

const PALETTE_SEARCH_PAGE_SIZE = 5;
const PALETTE_DEBOUNCE_MS = 300;

/**
 * Cmd/Ctrl+K (or `/`) launcher: static navigation commands plus a live,
 * cross-entity search (the same `GlobalSearchService` the dedicated
 * `/search` page uses) — grouped by entity type, with a trailing link to
 * the full results page for anything beyond this palette's top few
 * matches per type.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const { data: profile } = useCurrentUser();
  const debouncedQuery = useDebouncedValue(query, PALETTE_DEBOUNCE_MS);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTyping = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA";
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((previous) => !previous);
      } else if (event.key === "/" && !isTyping) {
        event.preventDefault();
        setOpen(true);
      }
    }
    function handleOpenEvent() {
      setOpen(true);
    }
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener(OPEN_COMMAND_PALETTE_EVENT, handleOpenEvent);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener(OPEN_COMMAND_PALETTE_EVENT, handleOpenEvent);
    };
  }, []);

  useEffect(() => {
    if (debouncedQuery.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    searchService
      .search({ q: debouncedQuery.trim(), pageSize: PALETTE_SEARCH_PAGE_SIZE })
      .then((result) => {
        if (!cancelled) setResults(result.data);
      })
      .catch(() => {
        if (!cancelled) setResults([]);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery]);

  function runCommand(action: () => void) {
    setOpen(false);
    action();
  }

  const groupedResults = groupByEntityType(results);

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput
        placeholder="Type a command or search everything..."
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        <CommandGroup heading="Navigation">
          <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.dashboard))}>
            <LayoutDashboard /> Dashboard
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.requests))}>
            <FileText /> Requests
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.newRequest))}>
            <Plus /> New request
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.approvals))}>
            <CheckSquare /> Approvals
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.analytics))}>
            <BarChart3 /> Analytics
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.notifications))}>
            <Bell /> Notifications
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.activity))}>
            <Activity /> Activity
          </CommandItem>
          {profile?.role === "admin" && (
            <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.workflows))}>
              <GitBranch /> Workflows
            </CommandItem>
          )}
          {profile?.role === "admin" && (
            <CommandItem onSelect={() => runCommand(() => router.push(ROUTES.admin))}>
              <ShieldCheck /> Admin
            </CommandItem>
          )}
          <CommandItem
            onSelect={() =>
              runCommand(() => setTheme(resolvedTheme === "dark" ? "light" : "dark"))
            }
          >
            {resolvedTheme === "dark" ? <Sun /> : <Moon />} Toggle theme
          </CommandItem>
        </CommandGroup>
        {groupedResults.map(([entityType, items]) => {
          const { icon: Icon, label } = getSearchEntityMeta(entityType);
          return (
            <CommandGroup key={entityType} heading={label}>
              {items.map((result) => {
                const href = getSearchResultHref(result);
                return (
                  <CommandItem
                    key={result.id}
                    value={result.title}
                    disabled={!href}
                    onSelect={() => href && runCommand(() => router.push(href))}
                  >
                    <Icon /> {result.title}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          );
        })}
        {results.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup>
              <CommandItem
                value={`view-all-results-${debouncedQuery.trim()}`}
                onSelect={() =>
                  runCommand(() => router.push(ROUTES.searchWithQuery(debouncedQuery.trim())))
                }
              >
                <SearchIcon /> View all results for &ldquo;{debouncedQuery.trim()}&rdquo;
              </CommandItem>
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
