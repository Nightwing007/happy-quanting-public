"use client";

import { Fragment, type ReactNode } from "react";
import { QueryError } from "@/components/query-error";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAlgoRules } from "@/lib/queries";

// A small renderer for the one document it shows: headings, bullet lists (one nesting level and
// wrapped lines), fenced code, paragraphs, `code` and **bold**. Not a general Markdown parser.

function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1)
      return (
        <code key={i} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">
          {part.slice(1, -1)}
        </code>
      );
    if (part.startsWith("**") && part.endsWith("**") && part.length > 3) return <strong key={i}>{part.slice(2, -2)}</strong>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

type Item = { depth: number; text: string };
type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "code"; text: string }
  | { kind: "list"; items: Item[] }
  | { kind: "para"; text: string };

function parse(md: string): Block[] {
  const blocks: Block[] = [];
  const lines = md.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i++;
      blocks.push({ kind: "code", text: body.join("\n") });
    } else if (/^#{1,6}\s/.test(line)) {
      const m = /^(#+)\s+(.*)$/.exec(line)!;
      blocks.push({ kind: "heading", level: m[1].length, text: m[2] });
      i++;
    } else if (/^\s*-\s/.test(line)) {
      const items: Item[] = [];
      while (i < lines.length && lines[i].trim() !== "" && !lines[i].startsWith("```")) {
        const m = /^(\s*)-\s+(.*)$/.exec(lines[i]);
        if (m) items.push({ depth: m[1].length >= 2 ? 1 : 0, text: m[2] });
        else if (items.length) items[items.length - 1].text += ` ${lines[i].trim()}`;
        i++;
      }
      blocks.push({ kind: "list", items });
    } else if (line.trim() === "") {
      i++;
    } else {
      const para: string[] = [];
      while (i < lines.length && lines[i].trim() !== "" && !/^(#{1,6}\s|\s*-\s|```)/.test(lines[i])) para.push(lines[i++].trim());
      blocks.push({ kind: "para", text: para.join(" ") });
    }
  }
  return blocks;
}

function Markdown({ source }: { source: string }) {
  return (
    <div className="grid gap-3 text-sm">
      {parse(source).map((b, i) => {
        if (b.kind === "heading")
          return b.level === 1 ? (
            <h2 key={i} className="text-lg font-semibold">
              {inline(b.text)}
            </h2>
          ) : (
            <h3 key={i} className="mt-2 font-semibold">
              {inline(b.text)}
            </h3>
          );
        if (b.kind === "code")
          return (
            <pre key={i} className="overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs leading-5">
              {b.text}
            </pre>
          );
        if (b.kind === "list")
          return (
            <ul key={i} className="grid gap-1.5">
              {b.items.map((it, j) => (
                <li key={j} className={`list-inside list-disc leading-snug ${it.depth ? "ml-5" : ""}`}>
                  {inline(it.text)}
                </li>
              ))}
            </ul>
          );
        return (
          <p key={i} className="leading-snug">
            {inline(b.text)}
          </p>
        );
      })}
    </div>
  );
}

/** The rules the checker enforces, rendered from the server's own copy so there is one source. */
export function RulesPanel() {
  const rules = useAlgoRules();
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>The rules</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {rules.error && <QueryError error={rules.error} title="Couldn't load the rules" onRetry={() => rules.refetch()} />}
        {rules.isPending && <Skeleton className="h-64 w-full" />}
        {rules.data && <Markdown source={rules.data.markdown} />}
      </CardContent>
    </Card>
  );
}
