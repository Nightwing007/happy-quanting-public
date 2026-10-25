import { Suspense } from "react";
import { EditorView } from "@/components/editor/editor-view";

export default function EditorPage() {
  // useSearchParams (?mine=<id>) needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <EditorView />
    </Suspense>
  );
}
