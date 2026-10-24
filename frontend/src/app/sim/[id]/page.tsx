import { Suspense } from "react";
import { SimRoute } from "@/components/sim/sim-view";

export default function SimSessionPage() {
  // The id is read on the client (useParams), which needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <SimRoute />
    </Suspense>
  );
}
