"use client";

import { Bookmark, Save, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";

/**
 * A generic "save the current filter state under a name, recall it
 * later" menu — used identically by Approvals and Analytics (previously
 * hand-rolled independently in each, byte-for-byte similar). Views are
 * frontend-only (no backend concept of a saved view exists) and keyed
 * only by `name`; every other field is opaque to this component.
 */
export function SavedViewsMenu<TView extends { name: string }>({
  views,
  onApply,
  onSave,
  onRemove,
}: {
  views: TView[];
  onApply: (view: TView) => void;
  onSave: (name: string) => void;
  onRemove: (name: string) => void;
}) {
  const [newViewName, setNewViewName] = useState("");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
        <Bookmark className="size-4" /> Saved views
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>Saved views</DropdownMenuLabel>
        {views.length === 0 && (
          <p className="px-2 py-1.5 text-xs text-muted-foreground">No saved views yet.</p>
        )}
        {views.map((view) => (
          <div
            key={view.name}
            className="flex items-center justify-between gap-1 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
          >
            <button type="button" className="flex-1 truncate text-left" onClick={() => onApply(view)}>
              {view.name}
            </button>
            <button
              type="button"
              aria-label={`Remove ${view.name}`}
              className="text-muted-foreground hover:text-destructive"
              onClick={(event) => {
                event.stopPropagation();
                onRemove(view.name);
              }}
            >
              <X className="size-3.5" />
            </button>
          </div>
        ))}
        <DropdownMenuSeparator />
        <div className="flex items-center gap-1 p-2">
          <Input
            value={newViewName}
            onChange={(event) => setNewViewName(event.target.value)}
            placeholder="New view name"
            className="h-8"
          />
          <Button
            size="icon-sm"
            variant="outline"
            aria-label="Save current view"
            disabled={!newViewName.trim()}
            onClick={() => {
              onSave(newViewName.trim());
              setNewViewName("");
            }}
          >
            <Save className="size-4" />
          </Button>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
