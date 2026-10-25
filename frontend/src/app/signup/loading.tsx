import { PageSkeleton, FormSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <FormSkeleton fields={3} className="mx-auto mt-8" />
    </PageSkeleton>
  );
}
