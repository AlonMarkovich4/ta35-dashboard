import { ils } from "@/lib/format";

type Leg = {
  action: string;
  type: string;
  strike: number;
  pricePts: number;
  priceNis: number;
};

export type Strategy = {
  id: number;
  name: string;
  emoji: string;
  tone: string; // class צבע לשם, e.g. "text-pos"
  wr: number | null;
  status: "profit_zone" | "near_breakeven" | "loss_zone";
  entryNis: number; // חיובי = עלות; שלילי = זיכוי
  maxProfitNis: number | null; // null = ∞
  maxLossNis: number;
  breakevens: number[];
  bePct: string;
  riskReward: number | null; // null = ∞
  yNowNis: number;
  legs: Leg[];
};

const STATUS: Record<
  Strategy["status"],
  { dot: string; border: string; ring: string }
> = {
  profit_zone: { dot: "🟢", border: "border-pos/40", ring: "ring-pos/15" },
  near_breakeven: { dot: "🟡", border: "border-warn/40", ring: "ring-warn/15" },
  loss_zone: { dot: "🔴", border: "border-neg/40", ring: "ring-neg/15" },
};

function wrColor(wr: number | null) {
  if (wr == null) return "text-text3";
  if (wr >= 0.55) return "text-pos";
  if (wr < 0.45) return "text-neg";
  return "text-warn";
}

const en = (n: number) => n.toLocaleString("en-US");

export function StrategyCard({ s }: { s: Strategy }) {
  const st = STATUS[s.status];
  const entryAbs = Math.abs(s.entryNis);
  const entryLabel = s.entryNis < 0 ? "קבלת זיכוי" : "עלות כניסה";
  const profitStr = s.maxProfitNis == null ? "∞" : ils(s.maxProfitNis);
  const rrStr = s.riskReward == null ? "ללא הגבלה ∞" : s.riskReward.toFixed(2);
  const beStr = s.breakevens.length ? s.breakevens.map(en).join(" – ") : "—";
  const wrStr = s.wr == null ? "—" : `${Math.round(s.wr * 100)}%`;

  return (
    <div
      className={`rounded-2xl border ${st.border} bg-surface/70 p-5 ring-1 ${st.ring} backdrop-blur`}
    >
      {/* header */}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className={`text-base font-bold ${s.tone}`}>
            <span className="ml-1">{s.emoji}</span> #{s.id} {s.name}
          </div>
          <div className="mt-0.5 text-[11px] text-text3">Win Rate היסטורי</div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`text-2xl font-extrabold tabular-nums ${wrColor(s.wr)}`}
            dir="ltr"
          >
            {wrStr}
          </span>
          <span className="text-xl leading-none">{st.dot}</span>
        </div>
      </div>

      {/* 3 numbers */}
      <div className="mb-4 flex text-center">
        <div className="flex-1 px-2">
          <div className="mb-1 text-[11px] text-text3">{entryLabel}</div>
          <div className="text-lg font-extrabold tabular-nums text-warn" dir="ltr">
            {ils(entryAbs)}
          </div>
        </div>
        <div className="w-px bg-border" />
        <div className="flex-1 px-2">
          <div className="mb-1 text-[11px] text-text3">רווח מקסימלי</div>
          <div className="text-lg font-extrabold tabular-nums text-pos" dir="ltr">
            {profitStr}
          </div>
        </div>
        <div className="w-px bg-border" />
        <div className="flex-1 px-2">
          <div className="mb-1 text-[11px] text-text3">הפסד מקסימלי</div>
          <div className="text-lg font-extrabold tabular-nums text-neg" dir="ltr">
            {ils(s.maxLossNis)}
          </div>
        </div>
      </div>

      {/* breakeven */}
      <div className="rounded-xl bg-surface2 px-4 py-3">
        <div className="text-sm">
          <span className="font-semibold text-text2">Breakeven: </span>
          <span className="font-bold tabular-nums text-text1" dir="ltr">
            {beStr}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-text3">{s.bePct}</div>
      </div>

      {/* trade detail */}
      <details className="mt-3">
        <summary className="cursor-pointer list-none rounded-lg px-3 py-2 text-sm text-text2 transition hover:bg-surface2 hover:text-text1">
          🛒 פרטי עסקה
        </summary>
        <div className="mt-2 space-y-3 px-1">
          <table className="w-full text-right text-sm">
            <tbody>
              <tr className="border-b border-border">
                <td className="py-1.5 text-text3">יחס רווח/סיכון</td>
                <td className="py-1.5 text-left font-semibold tabular-nums" dir="ltr">
                  {rrStr}
                </td>
              </tr>
              <tr className="border-b border-border">
                <td className="py-1.5 text-text3">P&amp;L במחיר הנוכחי</td>
                <td
                  className={`py-1.5 text-left font-semibold tabular-nums ${s.yNowNis >= 0 ? "text-pos" : "text-neg"}`}
                  dir="ltr"
                >
                  {s.yNowNis >= 0 ? "+" : ""}
                  {en(s.yNowNis)} ₪
                </td>
              </tr>
              <tr>
                <td className="py-1.5 text-text3">Breakeven מדויק</td>
                <td className="py-1.5 text-left font-semibold tabular-nums" dir="ltr">
                  {beStr}
                </td>
              </tr>
            </tbody>
          </table>

          <div>
            <div className="mb-1 text-xs font-semibold text-text2">
              מה לקנות בפועל:
            </div>
            <table className="w-full text-right text-xs">
              <thead>
                <tr className="text-text3">
                  <th className="pb-1 font-medium">פעולה</th>
                  <th className="pb-1 font-medium">סוג</th>
                  <th className="pb-1 font-medium">סטרייק</th>
                  <th className="pb-1 font-medium">מחיר נק&apos;</th>
                  <th className="pb-1 font-medium">עלות ₪</th>
                </tr>
              </thead>
              <tbody>
                {s.legs.map((lg, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-1 text-text2">{lg.action}</td>
                    <td className="py-1 text-text2">{lg.type}</td>
                    <td className="py-1 tabular-nums text-text2">{en(lg.strike)}</td>
                    <td className="py-1 tabular-nums text-text2">
                      {lg.pricePts.toFixed(1)}
                    </td>
                    <td className="py-1 tabular-nums text-text2">{en(lg.priceNis)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </details>

      {/* payoff — שלב 5 */}
      <div className="mt-1 rounded-lg px-3 py-2 text-sm text-text3">
        📈 Payoff Diagram — ייבנה בשלב 5
      </div>
    </div>
  );
}
