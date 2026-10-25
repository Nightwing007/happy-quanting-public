import { Suspense } from "react";
import { DeploymentRoute } from "@/components/deployments/deployment-view";

export default function DeploymentPage() {
  // The id is read on the client (useParams), which needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <DeploymentRoute />
    </Suspense>
  );
}
