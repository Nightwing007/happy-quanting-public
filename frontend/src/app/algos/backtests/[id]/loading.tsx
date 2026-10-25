import { PageSkeleton, TitleSkeleton, StatGridSkeleton, ChartSkeleton, TableSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-56" />
      <StatGridSkeleton count={6} />
      <ChartSkeleton />
      <TableSkeleton rows={4} />
    </PageSkeleton>
  );
}
