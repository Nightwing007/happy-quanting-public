"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { MoonIcon, SunIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SymbolSearch } from "@/components/symbol-search";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/trade", label: "Trade" },
  { href: "/sim", label: "Sim" },
  { href: "/orders", label: "Orders" },
  { href: "/payouts", label: "Payouts" },
  { href: "/settings", label: "Settings" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <header className="sticky top-0 z-40 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex min-h-14 max-w-7xl flex-wrap items-center gap-x-2 px-4">
        <Link href="/" className="mr-auto shrink-0 py-3 font-semibold tracking-tight sm:mr-0">
          <span className="sm:hidden">HQ</span>
          <span className="hidden sm:inline">Happy Quanting</span>
        </Link>

        <nav aria-label="Main" className="order-last flex basis-full items-center gap-0.5 overflow-x-auto pb-2 sm:order-none sm:ml-4 sm:min-w-0 sm:flex-1 sm:basis-auto sm:pb-0">
          {NAV.map(({ href, label }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-1.5 py-1.5 text-xs sm:text-sm transition-colors hover:bg-muted sm:px-3",
                  active ? "bg-muted font-medium text-foreground" : "text-muted-foreground",
                )}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        <SymbolSearch />

        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle light and dark theme"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          <SunIcon className="hidden dark:block" />
          <MoonIcon className="dark:hidden" />
        </Button>
      </div>
    </header>
  );
}
