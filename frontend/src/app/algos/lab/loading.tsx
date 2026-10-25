import { PageSkeleton, TitleSkeleton, SplitSkeleton, FormSkeleton, PanelSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-32" />
      <SplitSkeleton main={[<PanelSkeleton key="r" height="h-80" />]} side={[<FormSkeleton key="f" fields={4} className="max-w-none" />]} />
    </PageSkeleton>
  );
}
