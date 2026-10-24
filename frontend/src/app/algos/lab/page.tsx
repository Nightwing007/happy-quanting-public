import { Suspense } from "react";
import { LabView } from "@/components/algos/lab-view";

export default function LabPage() {
  // useSearchParams needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <LabView />
    </Suspense>
  );
}
