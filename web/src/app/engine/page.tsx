import { EngineView } from "./EngineView";
import { getCurrentDecision, getDecisionLogs, getValidation } from "@/lib/data";

// Always read fresh from the DB.
export const dynamic = "force-dynamic";

export default async function EnginePage() {
  const [decision, logs, validation] = await Promise.all([
    getCurrentDecision(),
    getDecisionLogs(50),
    getValidation(),
  ]);

  return <EngineView decision={decision} logs={logs} validation={validation} />;
}
