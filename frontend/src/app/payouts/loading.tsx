import { PageSkeleton, TitleSkeleton, CardGridSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-32" />
      <CardGridSkeleton count={4} height="h-32" />
    </PageSkeleton>
  );
}
