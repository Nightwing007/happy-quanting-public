import Link from "next/link";
import { cn } from "@/lib/utils";

/** The frosted pill with a round arrow (-45deg at rest, straight on hover). For headline calls to action on hub
 *  pages; dense forms keep the plain Button. */
export function Cta({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) {
  return (
    <Link href={href} className={cn("cta", className)}>
      <span className="cta-pill">{children}</span>
      <span className="cta-round" aria-hidden="true">
        <svg className="cta-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </span>
    </Link>
  );
}
