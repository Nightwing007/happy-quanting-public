import { NewSimForm } from "@/components/sim/new-sim-form";
import { SimList } from "@/components/sim/sim-list";
import { PageHeader } from "@/components/motion/page-header";

export default function SimPage() {
  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader
        title="Simulation"
        eyebrow="Replay"
        description="Replay a past trading day bar by bar, at any speed, with its own cash. You only ever see bars that had finished by the replayed clock."
      />
      <SimList />
      <NewSimForm />
    </div>
  );
}
