import { PageSkeleton, TitleSkeleton, FormSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-32" />
      <FormSkeleton fields={4} />
    </PageSkeleton>
  );
}
