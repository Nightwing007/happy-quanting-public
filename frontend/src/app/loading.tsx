import { PageSkeleton, TitleSkeleton, StatGridSkeleton, SplitSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-40" />
      <StatGridSkeleton />
      <SplitSkeleton />
    </PageSkeleton>
  );
}
