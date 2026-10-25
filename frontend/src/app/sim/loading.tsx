import { PageSkeleton, TitleSkeleton, CardGridSkeleton, TableSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-40" />
      <CardGridSkeleton count={3} height="h-32" />
      <TableSkeleton rows={4} />
    </PageSkeleton>
  );
}
