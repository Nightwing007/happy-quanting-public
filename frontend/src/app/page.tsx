import { PageHeader } from "@/components/motion/page-header";
import { Rise } from "@/components/motion/rise";
import { DeploymentsCard } from "@/components/dashboard/deployments-card";
import { CostsCard } from "@/components/dashboard/costs-card";
import { GettingStartedCard } from "@/components/dashboard/getting-started-card";
import { OpenTradesCard } from "@/components/dashboard/open-trades-card";
import { PositionsCard } from "@/components/dashboard/positions-card";
import { SummaryCards } from "@/components/dashboard/summary-cards";
import { WatchlistCard } from "@/components/dashboard/watchlist-card";

export default function DashboardPage() {
  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader title="Dashboard" eyebrow="Your paper account" />
      <Rise i={1}>
        <SummaryCards />
      </Rise>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Rise i={2} className="grid min-w-0 grid-cols-1 content-start gap-4">
          <GettingStartedCard />
          <PositionsCard />
          <DeploymentsCard />
          <OpenTradesCard />
        </Rise>
        <Rise i={3} className="grid min-w-0 grid-cols-1 content-start gap-4">
          <CostsCard />
          <WatchlistCard />
        </Rise>
      </div>
    </div>
  );
}
