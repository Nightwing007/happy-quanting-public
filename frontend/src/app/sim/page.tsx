import { NewSimForm } from "@/components/sim/new-sim-form";
import { SimList } from "@/components/sim/sim-list";

export default function SimPage() {
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Simulation</h1>
        <p className="text-sm text-muted-foreground">
          Replay a past trading day bar by bar, at any speed, with its own cash. You only ever see bars that had
          finished by the replayed clock.
        </p>
      </div>
      <SimList />
      <NewSimForm />
    </div>
  );
}
