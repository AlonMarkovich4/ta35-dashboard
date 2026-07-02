import { HistoricalView } from "./HistoricalView";
import { getHistorical } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function HistoricalPage() {
  const data = await getHistorical();
  return <HistoricalView data={data} />;
}
