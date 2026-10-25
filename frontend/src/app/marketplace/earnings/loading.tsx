import { PageSkeleton, TitleSkeleton, StatGridSkeleton, TableSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-40" />
      <StatGridSkeleton count={3} />
      <TableSkeleton rows={5} />
    </PageSkeleton>
  );
}
