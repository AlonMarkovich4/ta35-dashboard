import { EngineView } from "./EngineView";
import { getCurrentDecision, getDecisionLogs } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function EnginePage() {
  const [decision, logs] = await Promise.all([
    getCurrentDecision(),
    getDecisionLogs(50),
  ]);

  return <EngineView decision={decision} logs={logs} />;
}
