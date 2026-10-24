import { Suspense } from "react";
import { ListingRoute } from "@/components/marketplace/listing-view";

export default function ListingPage() {
  // The id is read on the client (useParams), which needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <ListingRoute />
    </Suspense>
  );
}
