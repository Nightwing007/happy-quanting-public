"use client";

import { useBadgeCatalog } from "@/lib/queries";
import { BadgeIcon } from "./badge-icon";
import { BadgeTip } from "./badge-tip";

/** A creator's Elite Four and Champion badges as small icons with tooltips (marketplace cards). */
export function CreatorBadges({ ids }: { ids: string[] }) {
  const catalog = useBadgeCatalog();
  if (ids.length === 0) return null;
  const byId = new Map((catalog.data?.regions ?? []).flatMap((r) => r.badges).map((b) => [b.id, b]));
  return (
    <span className="flex shrink-0 items-center gap-0.5" aria-label="Creator badges">
      {ids.map((id) => {
        const b = byId.get(id);
        const name = b?.name ?? id;
        return (
          <BadgeTip key={id} name={name} hint={b?.hint ?? ""} className="p-0.5" testId={`creator-badge-${id}`}>
            <BadgeIcon id={id} name={name} size="sm" />
          </BadgeTip>
        );
      })}
    </span>
  );
}
