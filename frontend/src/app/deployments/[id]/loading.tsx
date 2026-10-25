import { PageSkeleton, TitleSkeleton, StatGridSkeleton, PanelSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-64" />
      <StatGridSkeleton count={8} />
      <PanelSkeleton height="h-48" />
    </PageSkeleton>
  );
}
