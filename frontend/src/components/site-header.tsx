"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { ChevronDownIcon, MoonIcon, SunIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SymbolSearch } from "@/components/symbol-search";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { LiveDot } from "@/components/motion/live-dot";
import { UserAvatar } from "@/components/user-avatar";
import { useHealth, useHosted, useLogout, useMe, useMyBadges } from "@/lib/queries";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/trade", label: "Trade" },
  { href: "/sim", label: "Sim" },
];

type HftLink = { href: string; label: string; blurb: string; creatorsOnly?: boolean; code?: boolean };

// HFT is one box with three titled sections; every entry has a one-line description.
const HFT: { title: string; links: HftLink[] }[] = [
  {
    title: "Algo",
    links: [
      { href: "/algos", label: "Gallery", blurb: "The five built-in strategies." },
      { href: "/algos/lab", label: "Lab", blurb: "Tune a strategy and test it on history." },
      { href: "/algos#mine-heading", label: "My algorithms", blurb: "Strategies you saved." },
      { href: "/algos/backtests", label: "Backtests", blurb: "Every test you have run." },
      { href: "/deployments", label: "Deployments", blurb: "Your algorithms running live on paper." },
    ],
  },
  {
    title: "Market",
    links: [
      { href: "/marketplace", label: "Marketplace", blurb: "Follow strategies other people publish." },
      { href: "/marketplace/subscriptions", label: "My subscriptions", blurb: "Strategies you follow, and what they made." },
      { href: "/marketplace/earnings", label: "Earnings", blurb: "What your listings have earned.", creatorsOnly: true },
    ],
  },
  {
    title: "Create",
    links: [
      { href: "/create/editor", label: "Code editor", blurb: "Write a strategy in Python.", code: true },
      { href: "/create/blocks", label: "Block editor", blurb: "Build one by connecting blocks." },
      { href: "/create/upload", label: "Upload", blurb: "Check code and publish it.", code: true },
      { href: "/create", label: "My listings", blurb: "Versions, status and performance." },
    ],
  },
];

const HFT_PREFIXES = ["/algos", "/marketplace", "/create", "/creators", "/deployments"];

const noSubscribe = () => () => {};

export function SiteHeader() {
  const pathname = usePathname();
  const { resolvedTheme, setTheme } = useTheme();
  const [scrolled, setScrolled] = useState(false);
  const bar = useRef<HTMLSpanElement>(null);

  // Transparent at the top, a solid panel after 16px. The progress hairline is written straight to
  // the DOM so scrolling never re-renders; state only flips when the 16px threshold is crossed.
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const y = window.scrollY;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      setScrolled(y > 16);
      if (bar.current) bar.current.style.transform = `scaleX(${max > 0 ? Math.min(1, y / max) : 0})`;
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  const hftActive = HFT_PREFIXES.some((p) => pathname.startsWith(p));

  return (
    <header
      data-scrolled={scrolled || undefined}
      className={cn(
        "sticky top-0 z-40 border-b transition-colors duration-200 ease-out-expo",
        scrolled ? "border-line bg-ink" : "border-transparent bg-transparent",
      )}
    >
      <span
        ref={bar}
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-[-1px] h-px origin-left scale-x-0 bg-primary"
      />
      <div className="mx-auto flex min-h-14 max-w-7xl flex-wrap items-center gap-x-2 px-4">
        <Link href="/" className="t-display mr-auto shrink-0 py-3 text-xl tracking-[0.04em] sm:mr-0">
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
                className={cn(navItem, active ? navActive : navIdle)}
              >
                {label}
              </Link>
            );
          })}
          <HftMenu active={hftActive} pathname={pathname} />
        </nav>

        <StatusTag />
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

const navItem =
  "relative flex shrink-0 items-center gap-1 px-2.5 py-2 text-sm font-medium transition-colors duration-200 ease-out-expo hover:text-foreground after:absolute after:inset-x-2.5 after:bottom-0 after:h-0.5 after:origin-left after:scale-x-0 after:bg-primary after:transition-transform after:duration-300 after:ease-out-expo";
const navActive = "text-foreground after:scale-x-100";
const navIdle = "text-muted-foreground hover:after:scale-x-100";
// HFT is the studio (algos, marketplace, create), so it always stands out: an accent pill with the
// lamp glow, brighter on hover. Listed after navIdle so its text colour wins over the muted one.
const hftHighlight =
  "ml-1 border border-primary/60 bg-primary/12 font-semibold !text-primary shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_16%,transparent),0_0_14px_color-mix(in_oklab,var(--primary)_40%,transparent)] hover:bg-primary/20 motion-safe:transition-[background-color,box-shadow]";

/** The data-source tag that used to float under the header: a lamp and a short label, only for demo data. */
function StatusTag() {
  const { data } = useHealth();
  // The query cache can have the result on the browser's first render but never on the server's.
  const mounted = useSyncExternalStore(noSubscribe, () => true, () => false);
  if (!mounted || data?.data_source !== "fake") return null;
  return (
    <span className="t-meta flex shrink-0 items-center gap-1.5 border border-line-hot px-1.5 py-1 text-[10px] tracking-[0.08em] text-muted-foreground">
      <LiveDot tone="warn" pulse={false} className="size-1.5" />
      Offline demo data
    </span>
  );
}

function HftMenu({ active, pathname }: { active: boolean; pathname: string }) {
  const [open, setOpen] = useState(false);
  const { data: user } = useMe();
  const hosted = useHosted();
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label="HFT menu"
        className={cn(navItem, hftHighlight, "cursor-pointer", active || open ? navActive : navIdle)}
      >
        HFT
        <ChevronDownIcon className={cn("size-3.5 transition-transform duration-200", open && "rotate-180")} aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={8}
        className="max-h-[75vh] w-[min(58rem,calc(100vw-1rem))] max-w-none overflow-y-auto rounded-none p-0"
      >
        <div className="ledger sm:grid-cols-3">
          {HFT.map((section) => (
            <section key={section.title} className="p-4">
              <h2 className="t-meta mb-2 text-dim">{section.title}</h2>
              <ul className="grid gap-0.5">
                {section.links
                  .filter((l) => (!l.creatorsOnly || user?.is_creator) && !(hosted && l.code))
                  .map((l) => {
                    const here = !l.href.includes("#") && pathname === l.href;
                    return (
                      <li key={l.href}>
                        <Link
                          href={l.href}
                          onClick={() => setOpen(false)}
                          aria-current={here ? "page" : undefined}
                          className="block px-2 py-1.5 transition-colors duration-200 hover:bg-wash"
                        >
                          <span className="flex items-center gap-1.5 text-sm font-medium">
                            {l.label}
                            {here && <LiveDot pulse={false} className="size-1.5" />}
                          </span>
                          <span className="block text-xs text-muted-foreground">{l.blurb}</span>
                        </Link>
                      </li>
                    );
                  })}
              </ul>
              {hosted && section.links.some((l) => l.code) && (
                <p className="mt-1 px-2 text-xs text-muted-foreground">Code upload is turned off on this hosted demo</p>
              )}
            </section>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function UserMenu() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const { data: user, isPending } = useMe();
  const logout = useLogout();
  const badges = useMyBadges(!!user);

  if (isPending) return null;
  if (!user) {
    return (
      <Link href="/login" className="px-2 py-1.5 text-sm font-medium hover:bg-accent">
        Log in
      </Link>
    );
  }

  const name = user.display_name || user.username;
  const item = "block px-2 py-1.5 text-sm hover:bg-wash";
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={`Account menu for ${name}`}
        className="flex items-center gap-2 p-1 text-sm hover:bg-accent sm:pr-2"
      >
        <UserAvatar name={name} url={user.avatar_url} />
        <span className="hidden max-w-32 truncate sm:inline">{name}</span>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-52 flex-col gap-0.5 rounded-none p-1">
        <Link href="/profile" onClick={() => setOpen(false)} className={item}>
          Profile
        </Link>
        <Link href="/badges" onClick={() => setOpen(false)} className={cn(item, "flex items-center justify-between")}>
          Badges
          {badges.data && (
            <span className="t-data text-xs text-muted-foreground" data-testid="menu-badge-count">
              {badges.data.earned.length}
            </span>
          )}
        </Link>
        <Link href="/orders" onClick={() => setOpen(false)} className={item}>
          Orders
        </Link>
        <Link href="/payouts" onClick={() => setOpen(false)} className={item}>
          Payouts
        </Link>
        <Link href="/settings" onClick={() => setOpen(false)} className={item}>
          Settings
        </Link>
        <button
          type="button"
          disabled={logout.isPending}
          onClick={() => logout.mutate(undefined, { onSuccess: () => router.replace("/login") })}
          className={cn(item, "border-t border-line text-left")}
        >
          Log out
        </button>
      </PopoverContent>
    </Popover>
  );
}
