import { Suspense } from "react";
import { UploadFlow } from "@/components/create/upload-flow";

export default function UploadPage() {
  // useSearchParams (update mode reads ?listing=) needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <UploadFlow />
    </Suspense>
  );
}
