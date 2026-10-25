import { PageSkeleton, TitleSkeleton, StatGridSkeleton, ChartSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-64" />
      <StatGridSkeleton count={3} />
      <ChartSkeleton />
    </PageSkeleton>
  );
}
