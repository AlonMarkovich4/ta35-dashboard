import { HomeView } from "./HomeView";
import { getHomeStatus } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function Home() {
  const status = await getHomeStatus();
  return <HomeView status={status} />;
}
