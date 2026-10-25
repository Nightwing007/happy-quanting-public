import { Suspense } from "react";
import { BlockEditorView } from "@/components/blocks/block-editor";

export default function BlocksPage() {
  // useSearchParams (?mine=<id>) needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <BlockEditorView />
    </Suspense>
  );
}
