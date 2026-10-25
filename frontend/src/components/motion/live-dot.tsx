import { cn } from "@/lib/utils";

/** The lamp: open market, running sim. Glow and pulse are reserved for this and the badge Champion. */
export function LiveDot({
  tone = "accent",
  pulse = true,
  label,
  className,
}: {
  tone?: "accent" | "up" | "warn" | "off";
  pulse?: boolean;
  /** Accessible name; without it the dot is decorative. */
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={cn("lamp", className)}
      data-tone={tone}
      data-pulse={pulse && tone !== "off" ? "" : undefined}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}
