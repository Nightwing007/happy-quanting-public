"use client";

import Link from "next/link";
import { ArrowUpRightIcon } from "lucide-react";
import { useDirectionalHover } from "@/components/motion/directional-hover";
import { PageHeader } from "@/components/motion/page-header";
import { Rise } from "@/components/motion/rise";
import { MyListings } from "@/components/create/my-listings";
import { HostedNote } from "@/components/hosted-note";
import { useHosted } from "@/lib/queries";

const WAYS = [
  { href: "/create/editor", title: "Code editor", blurb: "Write a strategy in Python, check it against the rules, test it." },
  { href: "/create/blocks", title: "Block editor", blurb: "Connect big blocks into a strategy. No code needed." },
  { href: "/create/upload", title: "Upload", blurb: "Validate finished code, preview a backtest and publish it." },
];

function Way({ href, title, blurb }: { href: string; title: string; blurb: string }) {
  const dh = useDirectionalHover({ flood: true });
  return (
    <Link
      href={href}
      className={`${dh.className} group/way grid min-h-32 content-between gap-6 p-5`}
      onPointerEnter={dh.onPointerEnter}
      onPointerLeave={dh.onPointerLeave}
    >
      <span className="flex items-start justify-between gap-3">
        <span className="t-head text-lg">{title}</span>
        <ArrowUpRightIcon className="size-5 shrink-0 -rotate-45 transition-transform duration-300 ease-out-expo group-hover/way:rotate-0" aria-hidden="true" />
      </span>
      <span className="text-sm text-muted-foreground">{blurb}</span>
    </Link>
  );
}

/** /create: the three ways to make a strategy, then the listings you already published. */
export function CreateHub() {
  const hosted = useHosted();
  // On a hosted demo only the block editor is left; the code entry points give way to a note.
  const ways = hosted ? WAYS.filter((w) => w.href === "/create/blocks") : WAYS;
  return (
    <div className="grid min-w-0 grid-cols-1 gap-6">
      <PageHeader
        title="Create"
        eyebrow="HFT"
        description="Make a strategy with code or with blocks, then publish it to the marketplace."
      />
      <Rise i={1}>
        <ul className={hosted ? "ledger grid-cols-1" : "ledger grid-cols-1 md:grid-cols-3"}>
          {ways.map((w) => (
            <li key={w.href}>
              <Way {...w} />
            </li>
          ))}
        </ul>
        {hosted && <HostedNote className="mt-3" />}
      </Rise>
      <Rise i={2}>
        <MyListings />
      </Rise>
    </div>
  );
}
