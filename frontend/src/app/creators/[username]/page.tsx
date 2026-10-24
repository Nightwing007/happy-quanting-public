import { Suspense } from "react";
import { CreatorRoute } from "@/components/marketplace/creator-view";

export default function CreatorPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <CreatorRoute />
    </Suspense>
  );
}
