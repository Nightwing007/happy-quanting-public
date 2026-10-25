import { Rise } from "@/components/motion/rise";
import { SplitFlap } from "@/components/motion/split-flap";
import { cn } from "@/lib/utils";

// Past this a title is a name (a listing, a strategy) rather than a heading: it stays plain Anton.
const MAX_FLAP_CHARS = 26;

/**
 * The one page header: split-flap title (letters only), optional mono eyebrow and description, actions on
 * the right, and a hairline underneath. Use it for every page's h1.
 */
export function PageHeader({
  title,
  eyebrow,
  description,
  actions,
  className,
}: {
  title: string;
  eyebrow?: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <Rise as="header" className={cn("flex flex-wrap items-end justify-between gap-x-4 gap-y-3 border-b border-line pb-4", className)}>
      <div className="min-w-0">
        {eyebrow && <p className="t-meta mb-2 text-dim">{eyebrow}</p>}
        <h1 className="min-w-0 text-[28px] leading-none sm:text-[36px]">
          {title.length <= MAX_FLAP_CHARS ? <SplitFlap text={title} /> : <span className="t-display break-words">{title}</span>}
        </h1>
        {description && <div className="mt-2 max-w-2xl text-sm text-muted-foreground">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </Rise>
  );
}
