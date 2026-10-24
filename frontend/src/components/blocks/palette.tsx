"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GLOSSARY, type TermId } from "@/lib/glossary";
import type { BlockSpec } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CATEGORY_BAR, CATEGORY_ORDER, CATEGORY_TITLES } from "./graph";
import { TEMPLATES, type Template } from "./templates";

// Blocks named after a glossary term; their hover adds the glossary's reading and rule of thumb.
const BLOCK_TERMS: Record<string, TermId> = {
  sma_cross: "crossover",
  price_vs_sma: "sma",
  rsi_below: "oversold",
  rsi_above: "overbought",
  breakout: "donchian",
  bollinger_touch: "bollinger",
  volume_spike: "volume",
  short: "short",
  stop_loss: "stop_loss",
  target: "target",
};

export const DRAG_TYPE = "application/x-hq-block";

/** Every block, grouped. Drag one onto the canvas, or click it to add it. */
export function Palette({
  blocks,
  onAdd,
  onTemplate,
}: {
  blocks: BlockSpec[];
  onAdd: (type: string) => void;
  onTemplate: (t: Template) => void;
}) {
  return (
    <div className="grid gap-4">
      <section className="grid gap-1.5">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Start from a template</h3>
        {TEMPLATES.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => onTemplate(t)}
            className="rounded-lg border bg-muted/40 px-3 py-2 text-left hover:bg-muted"
          >
            <span className="block text-sm font-medium">{t.name}</span>
            <span className="block text-xs text-muted-foreground">{t.blurb}</span>
          </button>
        ))}
      </section>
      {CATEGORY_ORDER.map((category) => {
        const items = blocks.filter((b) => b.category === category);
        if (items.length === 0 && category !== "custom") return null;
        return (
          <section key={category} className="grid gap-1.5" aria-label={CATEGORY_TITLES[category]}>
            <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {CATEGORY_TITLES[category]}
            </h3>
            {items.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Nothing yet. Select blocks and choose &ldquo;Make a block&rdquo;, or write a code block.
              </p>
            )}
            {items.map((b) => (
              <Tooltip key={b.type}>
                <TooltipTrigger
                  render={
                    <button
                      type="button"
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData(DRAG_TYPE, b.type);
                        e.dataTransfer.effectAllowed = "copy";
                      }}
                      onClick={() => onAdd(b.type)}
                      className="flex min-w-0 items-stretch overflow-hidden rounded-lg border bg-card text-left hover:bg-muted"
                    />
                  }
                >
                  <span className={cn("w-1.5 shrink-0", CATEGORY_BAR[b.category])} />
                  <span className="grid min-w-0 gap-0.5 px-2.5 py-1.5">
                    <span className="text-sm font-medium">{b.label}</span>
                    {/* Touch screens have no hover, so the help is also printed under the name there. */}
                    <span className="text-xs text-muted-foreground lg:hidden">{b.help}</span>
                  </span>
                </TooltipTrigger>
                <TooltipContent side="right" className="block">
                  {b.help}
                  {BLOCK_TERMS[b.type] && (
                    <span className="mt-1 block opacity-80">
                      {GLOSSARY[BLOCK_TERMS[b.type]].read}
                      {" "}
                      {(GLOSSARY[BLOCK_TERMS[b.type]] as { good?: string }).good}
                    </span>
                  )}
                </TooltipContent>
              </Tooltip>
            ))}
          </section>
        );
      })}
    </div>
  );
}
