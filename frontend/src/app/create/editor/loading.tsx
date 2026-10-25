import { PageSkeleton, TitleSkeleton, SplitSkeleton, ChartSkeleton, PanelSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-40" />
      <SplitSkeleton main={[<ChartSkeleton key="e" className="sm:h-[28rem]" />]} side={[<PanelSkeleton key="p" height="h-48" />]} />
    </PageSkeleton>
  );
}
