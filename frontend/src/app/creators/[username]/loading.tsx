import { PageSkeleton, TitleSkeleton, StatGridSkeleton, CardGridSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-48" />
      <StatGridSkeleton count={3} />
      <CardGridSkeleton count={3} height="h-44" />
    </PageSkeleton>
  );
}
