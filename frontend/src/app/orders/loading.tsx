import { PageSkeleton, TitleSkeleton, TableSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-32" />
      <TableSkeleton rows={8} />
    </PageSkeleton>
  );
}
