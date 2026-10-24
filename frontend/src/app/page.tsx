import { CostsCard } from "@/components/dashboard/costs-card";
import { GettingStartedCard } from "@/components/dashboard/getting-started-card";
import { OpenTradesCard } from "@/components/dashboard/open-trades-card";
import { PositionsCard } from "@/components/dashboard/positions-card";
import { SummaryCards } from "@/components/dashboard/summary-cards";
import { WatchlistCard } from "@/components/dashboard/watchlist-card";

export default function DashboardPage() {
  return (
    <div className="grid grid-cols-1 gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
      <SummaryCards />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="grid min-w-0 grid-cols-1 content-start gap-4">
          <GettingStartedCard />
          <PositionsCard />
          <OpenTradesCard />
        </div>
        <div className="grid min-w-0 grid-cols-1 content-start gap-4">
          <CostsCard />
          <WatchlistCard />
        </div>
      </div>
    </div>
  );
}
