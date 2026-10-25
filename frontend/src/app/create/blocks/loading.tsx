import { PageSkeleton, TitleSkeleton, SplitSkeleton, ChartSkeleton, PanelSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-44" />
      <SplitSkeleton main={[<ChartSkeleton key="c" className="sm:h-[28rem]" />]} side={[<PanelSkeleton key="p" height="h-64" />]} />
    </PageSkeleton>
  );
}
