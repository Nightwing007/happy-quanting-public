// CSS-only (see .page-enter in globals.css); reduced motion removes the animation there.
export function PageTransition({ children }: { children: React.ReactNode }) {
  return <div className="page-enter min-w-0">{children}</div>;
}
