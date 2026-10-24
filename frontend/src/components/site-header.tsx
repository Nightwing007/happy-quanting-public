"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { MoonIcon, SunIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SymbolSearch } from "@/components/symbol-search";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { UserAvatar } from "@/components/user-avatar";
import { useLogout, useMe, useMyBadges } from "@/lib/queries";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/trade", label: "Trade" },
  { href: "/sim", label: "Sim" },
  { href: "/algos", label: "Algos" },
  { href: "/marketplace", label: "Market" },
  { href: "/create", label: "Create" },
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

        <UserMenu />
      </div>
    </header>
  );
}

function UserMenu() {
  const router = useRouter();
  const { data: user, isPending } = useMe();
  const logout = useLogout();
  const badges = useMyBadges(!!user);

  if (isPending) return null;
  if (!user) {
    return (
      <Link href="/login" className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
        Log in
      </Link>
    );
  }

  const name = user.display_name || user.username;
  return (
    <Popover>
      <PopoverTrigger
        aria-label={`Account menu for ${name}`}
        className="flex items-center gap-2 rounded-md p-1 text-sm hover:bg-muted sm:pr-2"
      >
        <UserAvatar name={name} url={user.avatar_url} />
        <span className="hidden max-w-32 truncate sm:inline">{name}</span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-48 gap-1 p-1">
        <Link href="/profile" className="rounded-md px-2 py-1.5 text-sm hover:bg-muted">
          Profile
        </Link>
        <Link href="/badges" className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-muted">
          Badges
          {badges.data && (
            <span className="text-xs tabular-nums text-muted-foreground" data-testid="menu-badge-count">
              {badges.data.earned.length}
            </span>
          )}
        </Link>
        <Link href="/marketplace/subscriptions" className="rounded-md px-2 py-1.5 text-sm hover:bg-muted">
          My subscriptions
        </Link>
        <Link href="/create" className="rounded-md px-2 py-1.5 text-sm hover:bg-muted">
          Create
        </Link>
        {user.is_creator && (
          <Link href="/marketplace/earnings" className="rounded-md px-2 py-1.5 text-sm hover:bg-muted">
            My earnings
          </Link>
        )}
        <button
          type="button"
          disabled={logout.isPending}
          onClick={() => logout.mutate(undefined, { onSuccess: () => router.replace("/login") })}
          className="rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
        >
          Log out
        </button>
      </PopoverContent>
    </Popover>
  );
}
