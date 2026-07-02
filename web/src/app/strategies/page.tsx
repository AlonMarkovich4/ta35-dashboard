import { StrategiesView } from "./StrategiesView";
import { getMoves } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function StrategiesPage() {
  const moves = await getMoves();
  return <StrategiesView moves={moves} />;
}
