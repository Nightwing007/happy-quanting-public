import { PageSkeleton, TitleSkeleton, CardGridSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-44" />
      <CardGridSkeleton count={6} height="h-44" />
    </PageSkeleton>
  );
}
