import { PaperView } from "./PaperView";
import { getPortfolios, getClosedSummary, getEquityCurve, getTrackRecord } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function PaperPage() {
  const [portfolios, summary, equity, track] = await Promise.all([
    getPortfolios(),
    getClosedSummary(),
    getEquityCurve(),
    getTrackRecord(),
  ]);

  return (
    <PaperView
      portfolios={portfolios}
      summary={summary}
      equity={equity}
      track={track}
    />
  );
}
