import { MarginView } from "./MarginView";
import { getMarginData } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function MarginPage() {
  const data = await getMarginData();
  return <MarginView data={data} />;
}
