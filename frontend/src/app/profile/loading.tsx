import { PageSkeleton, TitleSkeleton, FormSkeleton, CardGridSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-32" />
      <FormSkeleton fields={3} />
      <CardGridSkeleton count={3} height="h-24" />
    </PageSkeleton>
  );
}
