import { PageTransition } from "@/components/motion/page-transition";

// A template (unlike a layout) remounts on every navigation, which replays the entrance.
export default function Template({ children }: { children: React.ReactNode }) {
  return <PageTransition>{children}</PageTransition>;
}
