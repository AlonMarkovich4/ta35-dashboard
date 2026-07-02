import { UpcomingView } from "./UpcomingView";
import { getOptionChain } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function UpcomingPage() {
  // One chain to discover the available expiries, then fetch them all so the
  // expiry selector switches client-side (no server round-trip per change).
  const first = await getOptionChain();
  const chains = first
    ? (await Promise.all(first.availableExpiries.map((iso) => getOptionChain(iso)))).filter(
        (c): c is NonNullable<typeof c> => c != null,
      )
    : [];

  return <UpcomingView chains={chains} />;
}
