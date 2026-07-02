import { notFound } from "next/navigation";
import { PortfolioDetailView } from "./PortfolioDetailView";
import { getPortfolioDetail, getEquityCurve, getTrackRecord } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function PortfolioDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const pid = Number(id);
  if (!Number.isFinite(pid)) notFound();

  const [detail, equity, track] = await Promise.all([
    getPortfolioDetail(pid),
    getEquityCurve(pid),
    getTrackRecord(pid),
  ]);

  if (!detail) notFound();

  return <PortfolioDetailView detail={detail} equity={equity} track={track} />;
}
