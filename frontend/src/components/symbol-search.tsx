"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SearchIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useSearch } from "@/lib/queries";
import { ApiError } from "@/lib/api";

const DEBOUNCE_MS = 250;

export function SymbolSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(text), DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [text]);

  const typed = text.trim();
  const search = useSearch(debounced);
  // True from the first keystroke until results for the current text have arrived.
  const waiting = typed !== "" && (debounced.trim() !== typed || search.isFetching);
  const results = debounced.trim() === typed ? (search.data ?? []) : [];
  const errorMessage = search.isError
    ? search.error instanceof ApiError
      ? search.error.message
      : "Search failed."
    : null;

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setText("");
      setDebounced("");
    }
  }

  function go(symbol: string) {
    handleOpenChange(false);
    router.push(`/trade?symbol=${encodeURIComponent(symbol)}`);
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        aria-label="Search symbols"
        className="shrink-0 gap-2 text-muted-foreground"
      >
        <SearchIcon />
        <span className="hidden sm:inline">Search</span>
        <kbd className="hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">Ctrl K</kbd>
      </Button>

      <CommandDialog
        open={open}
        onOpenChange={handleOpenChange}
        title="Search symbols"
        description="Search for a stock, index, currency pair or crypto by name or symbol."
      >
        {/* Filtering happens on the server, so cmdk must not filter again. */}
        <Command shouldFilter={false}>
          <CommandInput value={text} onValueChange={setText} placeholder="Search by name or symbol..." />
          <CommandList>
            {typed === "" && (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                Type a company, index, currency pair or crypto name.
              </p>
            )}
            {waiting && <p className="px-3 py-3 text-center text-sm text-muted-foreground">Searching...</p>}
            {!waiting && errorMessage && (
              <p role="alert" className="px-3 py-3 text-center text-sm text-destructive">
                {errorMessage}
              </p>
            )}
            {!waiting && !errorMessage && typed !== "" && results.length === 0 && (
              <p className="px-3 py-3 text-center text-sm text-muted-foreground">No matches found.</p>
            )}

            {results.length > 0 && (
              <CommandGroup heading="Results">
                {results.map((r) => (
                  <CommandItem key={`${r.symbol}-${r.exchange}`} value={r.symbol} onSelect={() => go(r.symbol)}>
                    <span className="w-24 shrink-0 truncate font-medium">{r.symbol}</span>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">{r.name}</span>
                    <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">{r.exchange}</span>
                    <Badge variant="secondary" className="shrink-0">
                      {r.type}
                    </Badge>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {/* Below the results on purpose: Enter must pick a real result, not a symbol that may not exist. */}
            {typed !== "" && (
              <CommandGroup>
                <CommandItem value="__open-literal__" disabled={waiting} onSelect={() => go(typed.toUpperCase())}>
                  <span className="min-w-0 truncate">Open &ldquo;{typed}&rdquo; as a symbol</span>
                </CommandItem>
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  );
}
