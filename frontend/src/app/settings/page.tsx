"use client";

import { useState } from "react";
import { toast } from "sonner";
import { QueryError } from "@/components/query-error";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useBrokers, useSettings, useUpdateSettings } from "@/lib/queries";
import type { BrokerGroup, Settings } from "@/lib/types";
import { cn } from "@/lib/utils";

const FIELD: Record<string, keyof Settings> = {
  india: "broker_india",
  international: "broker_international",
  crypto: "broker_crypto",
};

function SegmentCard({
  group,
  saved,
  saving,
  error,
  onSave,
}: {
  group: BrokerGroup;
  saved: string;
  saving: boolean;
  error: string | null;
  onSave: (code: string) => void;
}) {
  // null = no pending change; the radio follows the saved value until the user picks another.
  // After a save succeeds the saved value catches up to the pick, so it is never reset by hand.
  const [picked, setPicked] = useState<string | null>(null);
  const selected = picked ?? saved;
  const dirty = selected !== saved;
  const name = `broker-${group.segment}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{group.label}</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-3">
        <div role="radiogroup" aria-label={`${group.label} broker`} className="grid grid-cols-1 gap-2">
          {group.brokers.map((b) => (
            <label
              key={b.code}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors hover:bg-muted/50",
                selected === b.code && "border-primary bg-muted/50",
              )}
            >
              <input
                type="radio"
                name={name}
                value={b.code}
                checked={selected === b.code}
                onChange={() => setPicked(b.code)}
                className="mt-1 size-4 shrink-0 accent-primary"
              />
              <span className="grid min-w-0 gap-1">
                <span className="font-medium">{b.name}</span>
                <span className="text-muted-foreground">{b.notes}</span>
                <span className="text-xs text-muted-foreground">
                  Markets: {b.markets.map((m) => m.name).join(", ")}
                </span>
              </span>
            </label>
          ))}
        </div>
        {error && (
          <Alert variant="destructive">
            <AlertDescription className="text-destructive">{error}</AlertDescription>
          </Alert>
        )}
        <div>
          <Button
            disabled={!dirty || saving}
            onClick={() => onSave(selected)}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const settings = useSettings();
  const brokers = useBrokers();
  const update = useUpdateSettings();
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [savingSegment, setSavingSegment] = useState<string | null>(null);

  function save(segment: string, code: string) {
    const field = FIELD[segment];
    setErrors((e) => ({ ...e, [segment]: null }));
    setSavingSegment(segment);
    update.mutate(
      { [field]: code },
      {
        onSuccess: () => toast.success("Broker saved. New orders will use it."),
        onError: (e) => setErrors((cur) => ({ ...cur, [segment]: e.message })),
        onSettled: () => setSavingSegment(null),
      },
    );
  }

  const loadError = settings.error ?? brokers.error;

  return (
    <div className="grid grid-cols-1 gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="max-w-2xl text-sm text-muted-foreground">
        Your broker decides the brokerage and currency-conversion fees on every trade, and which markets you can
        trade at all. Different brokers charge differently, but taxes and exchange fees are the same whichever one
        you pick.
      </p>
      {loadError && !(settings.data && brokers.data) && (
        <QueryError
          error={loadError}
          title="Couldn't load your settings"
          onRetry={() => {
            settings.refetch();
            brokers.refetch();
          }}
        />
      )}
      {!loadError && !(settings.data && brokers.data) && (
        <div className="grid grid-cols-1 gap-4">
          <Skeleton className="h-64 w-full" />
        </div>
      )}
      {settings.data && brokers.data && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {brokers.data.map((g) => (
            <SegmentCard
              key={g.segment}
              group={g}
              saved={settings.data[FIELD[g.segment]]}
              saving={savingSegment === g.segment}
              error={errors[g.segment] ?? null}
              onSave={(code) => save(g.segment, code)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
