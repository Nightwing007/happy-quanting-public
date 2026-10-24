"use client";

import { useId, useImperativeHandle, useMemo, useRef, useState } from "react";
import { UploadIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type CodeInputHandle = { focusLine: (line: number) => void };

// Gutter, highlight bands and textarea must share one line height and top padding to stay aligned.
const LINE_PX = 20;
const PAD_PX = 8;
const DEFAULT_MAX_BYTES = 50 * 1024;

type Props = {
  value: string;
  onChange: (value: string) => void;
  /** 1-based lines to mark. */
  problemLines: number[];
  maxBytes?: number;
  ref?: React.Ref<CodeInputHandle>;
};

const byteLength = (s: string) => new TextEncoder().encode(s).length;

/** A plain monospace textarea with a line-number gutter and red bands behind lines that have problems. */
export function CodeInput({ value, onChange, problemLines, maxBytes = DEFAULT_MAX_BYTES, ref }: Props) {
  const id = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [fileError, setFileError] = useState<string | null>(null);

  const lineCount = useMemo(() => value.split("\n").length, [value]);
  const flagged = useMemo(() => new Set(problemLines), [problemLines]);
  const bytes = byteLength(value);

  useImperativeHandle(ref, () => ({
    focusLine(line) {
      const el = area.current;
      if (!el || line < 1) return;
      const lines = value.split("\n");
      const idx = Math.min(line, lines.length) - 1;
      const start = lines.slice(0, idx).reduce((n, l) => n + l.length + 1, 0);
      el.focus({ preventScroll: true });
      el.setSelectionRange(start, start + lines[idx].length);
      el.scrollTop = Math.max(0, idx * LINE_PX - 2 * LINE_PX);
    },
  }));

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // the same file can be chosen again after an edit
    if (!file) return;
    if (file.size > maxBytes) {
      setFileError(`That file is ${(file.size / 1024).toFixed(1)} KB; the limit is ${Math.round(maxBytes / 1024)} KB.`);
      return;
    }
    setFileError(null);
    onChange(await file.text());
  }

  const lines = Array.from({ length: lineCount }, (_, i) => i + 1);
  return (
    <div className="grid min-w-0 gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInput}
          id={`${id}-file`}
          type="file"
          accept=".py,text/x-python,text/plain"
          aria-label="Upload a .py file"
          onChange={onFile}
          className="sr-only"
          tabIndex={-1}
        />
        <Button type="button" variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
          <UploadIcon />
          Upload a .py file
        </Button>
        <span className="text-xs text-muted-foreground">or paste your code below (up to {Math.round(maxBytes / 1024)} KB).</span>
      </div>
      {fileError && (
        <p role="alert" className="text-xs text-destructive">
          {fileError}
        </p>
      )}
      <div className="flex h-96 min-w-0 overflow-hidden rounded-lg border border-input bg-background font-mono text-xs focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
        <div
          aria-hidden
          className="shrink-0 select-none overflow-hidden border-r bg-muted/50 text-right text-muted-foreground"
          style={{ paddingTop: PAD_PX, lineHeight: `${LINE_PX}px` }}
        >
          <div style={{ transform: `translateY(${-scrollTop}px)` }}>
            {lines.map((n) => (
              <div key={n} className={cn("px-2", flagged.has(n) && "bg-destructive/20 font-semibold text-destructive")}>
                {n}
              </div>
            ))}
          </div>
        </div>
        <div className="relative min-w-0 flex-1">
          <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden" style={{ paddingTop: PAD_PX }}>
            <div style={{ transform: `translateY(${-scrollTop}px)` }}>
              {lines.map((n) => (
                <div key={n} style={{ height: LINE_PX }} className={flagged.has(n) ? "bg-destructive/15" : undefined} />
              ))}
            </div>
          </div>
          <textarea
            ref={area}
            aria-label="Strategy code"
            value={value}
            wrap="off"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            placeholder={"import hq\n\nclass MyStrategy(hq.Strategy):\n    ..."}
            onChange={(e) => onChange(e.target.value)}
            onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
            className="relative block size-full resize-none overflow-auto whitespace-pre bg-transparent px-2 outline-none"
            style={{ paddingTop: PAD_PX, paddingBottom: PAD_PX, lineHeight: `${LINE_PX}px` }}
          />
        </div>
      </div>
      <p className={cn("text-xs", bytes > maxBytes ? "text-destructive" : "text-muted-foreground")}>
        {lineCount} {lineCount === 1 ? "line" : "lines"}, {(bytes / 1024).toFixed(1)} KB
        {bytes > maxBytes ? ` (over the ${Math.round(maxBytes / 1024)} KB limit)` : ""}
      </p>
    </div>
  );
}
