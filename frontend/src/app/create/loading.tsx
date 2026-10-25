import { PageSkeleton, TitleSkeleton, TableSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-40" />
      <TableSkeleton rows={5} />
    </PageSkeleton>
  );
}
