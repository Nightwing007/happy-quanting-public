import { PageSkeleton, TitleSkeleton, ChartSkeleton, SplitSkeleton, PanelSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-64" />
      <SplitSkeleton main={[<ChartSkeleton key="c" />]} side={[<PanelSkeleton key="t" height="h-64" />]} />
    </PageSkeleton>
  );
}
