"use client";

import { useEffect, useImperativeHandle, useRef } from "react";
import Editor, { loader, type OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import { useTheme } from "next-themes";
import { CTX_MEMBERS, INDICATOR_FUNCTIONS, type Hint } from "@/lib/hq-api-hints";
import type { CodeProblem } from "@/lib/types";

// Monaco comes from the bundled `monaco-editor` package, not the default CDN, so the editor works
// offline. Only the editor worker is needed (Python is highlighted on the main thread).
if (typeof window !== "undefined") {
  (self as unknown as { MonacoEnvironment: monaco.Environment }).MonacoEnvironment = {
    getWorker: () => new Worker(new URL("monaco-editor/editor/editor.worker.js", import.meta.url), { type: "module" }),
  };
  loader.config({ monaco });
}

export type CodeEditorHandle = { reveal: (line: number, col: number) => void };

type Props = {
  value: string;
  onChange: (value: string) => void;
  problems: CodeProblem[];
  ref?: React.Ref<CodeEditorHandle>;
};

const MARKER_OWNER = "hq-validate";

function items(hints: Hint[], range: monaco.IRange): monaco.languages.CompletionItem[] {
  return hints.map((h) => ({
    label: { label: h.name, detail: h.signature },
    kind: h.kind === "method" ? monaco.languages.CompletionItemKind.Method : monaco.languages.CompletionItemKind.Property,
    insertText: h.snippet ?? h.name,
    insertTextRules: h.snippet ? monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet : undefined,
    documentation: h.doc,
    range,
  }));
}

/** Completion for `ctx.` and `ctx.indicators.` (the lists live in `lib/hq-api-hints.ts`). */
function registerHqCompletions(): monaco.IDisposable {
  return monaco.languages.registerCompletionItemProvider("python", {
    triggerCharacters: ["."],
    provideCompletionItems(model, position) {
      const before = model.getValueInRange({
        startLineNumber: position.lineNumber,
        startColumn: 1,
        endLineNumber: position.lineNumber,
        endColumn: position.column,
      });
      const word = model.getWordUntilPosition(position);
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      };
      if (/\bctx\.indicators\.\w*$/.test(before)) return { suggestions: items(INDICATOR_FUNCTIONS, range) };
      if (/\bctx\.\w*$/.test(before)) return { suggestions: items(CTX_MEMBERS, range) };
      return { suggestions: [] };
    },
  });
}

/** Markers follow the latest report; line 0 (a whole-file problem) is pinned to line 1. */
function applyMarkers(editor: monaco.editor.IStandaloneCodeEditor, problems: CodeProblem[]) {
  const model = editor.getModel();
  if (!model) return;
  const lines = model.getLineCount();
  monaco.editor.setModelMarkers(
    model,
    MARKER_OWNER,
    problems.map((p) => {
      const line = Math.min(Math.max(p.line, 1), lines);
      const column = p.line < 1 ? 1 : Math.max(1, p.col);
      const word = model.getWordAtPosition({ lineNumber: line, column });
      return {
        severity: monaco.MarkerSeverity.Error,
        message: p.message.replace(/^Line \d+:\s*/, ""),
        startLineNumber: line,
        startColumn: column,
        endLineNumber: line,
        endColumn: Math.max(word?.endColumn ?? column + 1, column + 1),
        code: p.code,
      };
    }),
  );
}

/** Monaco with the Python language, the app theme, the `hq` autocomplete and validator markers. */
export default function CodeEditor({ value, onChange, problems, ref }: Props) {
  const { resolvedTheme } = useTheme();
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const completions = useRef<monaco.IDisposable | null>(null);

  useImperativeHandle(ref, () => ({
    reveal(line, col) {
      const editor = editorRef.current;
      if (!editor || line < 1) return;
      editor.revealLineInCenter(line);
      editor.setPosition({ lineNumber: line, column: Math.max(1, col) });
      editor.focus();
    },
  }));

  useEffect(() => () => completions.current?.dispose(), []);

  useEffect(() => {
    if (editorRef.current) applyMarkers(editorRef.current, problems);
  }, [problems]);

  const onMount: OnMount = (editor) => {
    editorRef.current = editor;
    completions.current?.dispose();
    completions.current = registerHqCompletions();
    applyMarkers(editor, problems); // a report may have arrived before the editor was ready
  };

  return (
    <div className="h-[28rem] min-w-0 overflow-hidden rounded-lg border">
      <Editor
        height="100%"
        language="python"
        theme={resolvedTheme === "dark" ? "vs-dark" : "vs"}
        value={value}
        onChange={(v) => onChange(v ?? "")}
        onMount={onMount}
        loading={<p className="p-3 text-sm text-muted-foreground">Loading the editor...</p>}
        options={{
          minimap: { enabled: false },
          fontSize: 13,
          tabSize: 4,
          insertSpaces: true,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          wordWrap: "off",
          quickSuggestions: { other: true, comments: false, strings: false },
        }}
      />
    </div>
  );
}
