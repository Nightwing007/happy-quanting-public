import { cn } from "cn"

// The shimmer lives in globals.css (.skeleton) and switches off under prefers-reduced-motion.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("skeleton", className)}
      {...props}
    />
  )
}

export { Skeleton }
