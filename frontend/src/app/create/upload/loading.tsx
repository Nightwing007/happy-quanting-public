import { PageSkeleton, TitleSkeleton, SplitSkeleton, FormSkeleton, PanelSkeleton } from "@/components/motion/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TitleSkeleton width="w-48" />
      <SplitSkeleton main={[<PanelSkeleton key="c" height="h-72" />]} side={[<FormSkeleton key="f" fields={4} className="max-w-none" />]} />
    </PageSkeleton>
  );
}
