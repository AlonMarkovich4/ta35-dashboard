"use client";

import { useState, useMemo } from "react";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { Card } from "@/components/ui/Card";
import { Refresh } from "@/components/icons";
import { ChainChart } from "@/components/charts/ChainChart";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Empty } from "@/components/ui/Empty";
import { en } from "@/lib/format";
import { strategyBuilder, type StrategyStrikes } from "@/lib/strategyBuilder";
import type { OptionChain, ChainRow, CurrentDecision } from "@/lib/data";

// מטא סטטי לתצוגה (שם/אייקון/צבע) — הסטרייקים וה-P&L מגיעים מ-strategyBuilder החי
const STRAT_META: Record<number, { name: string; emoji: string; tone: string }> = {
  1: { name: "Bull Call Spread", emoji: "📈", tone: "text-pos" },
  2: { name: "Short Iron Condor", emoji: "🦅", tone: "text-accent2" },
  3: { name: "Long Call Butterfly", emoji: "🦋", tone: "text-purple" },
  4: { name: "Long Put Butterfly", emoji: "🦋", tone: "text-purple" },
  5: { name: "Long Straddle", emoji: "⚡", tone: "text-warn" },
  6: { name: "Long Strangle", emoji: "🌪️", tone: "text-neg" },
};

const REGIME_MAP: Record<string, { label: string; tone: string }> = {
  calm: { label: "רגוע", tone: "text-pos" },
  normal: { label: "רגיל", tone: "text-accent2" },
  volatile: { label: "תנודתי", tone: "text-neg" },
};
const regimeInfo = (r: string) => REGIME_MAP[r] ?? { label: "לא ידוע", tone: "text-text3" };

// ─── real: strategy recommendation card ─────────────────────────────
function RecoCard({ id, s }: { id: number; s: StrategyStrikes }) {
  const m = STRAT_META[id];
  return (
    <Card className="p-5">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-lg">{m.emoji}</span>
        <span className={`font-bold ${m.tone}`}>{m.name}</span>
      </div>
      <div className="text-sm text-text1">{s.strikesDesc}</div>
      <div className="mt-1 font-mono text-xs text-text3" dir="ltr">{s.structure}</div>
      <div className="mt-3 space-y-1 text-xs text-text2">
        <div><span className="text-text3">עלות: </span><span className="tabular-nums">{s.costPts} נק'</span></div>
        <div><span className="text-text3">מקס' הפסד: </span>{s.maxLossDesc}</div>
        <div><span className="text-text3">מקס' רווח: </span>{s.maxProfitDesc}</div>
      </div>
    </Card>
  );
}

// ─── real: option chain table ───────────────────────────────────────
function ChainTable({ rows, atmStrike }: { rows: ChainRow[]; atmStrike: number | null }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-right text-xs">
        <thead>
          <tr className="text-text3">
            <th className="pb-2 font-medium">Strike</th>
            <th className="pb-2 font-medium">Call (נק&apos;)</th>
            <th className="pb-2 font-medium">δ Call</th>
            <th className="pb-2 font-medium">מחזור Call</th>
            <th className="pb-2 font-medium">Put (נק&apos;)</th>
            <th className="pb-2 font-medium">δ Put</th>
            <th className="pb-2 font-medium">מחזור Put</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const atmRow = r.strike === atmStrike;
            return (
              <tr key={r.strike} className={`border-t border-border ${atmRow ? "bg-pos/10" : ""}`}>
                <td className={`py-1.5 tabular-nums ${atmRow ? "font-bold text-pos" : "text-text1"}`}>{en(r.strike)}</td>
                <td className="py-1.5 tabular-nums text-text2">{r.callPts.toFixed(1)}</td>
                <td className="py-1.5 tabular-nums text-text3">{r.callDelta.toFixed(2)}</td>
                <td className="py-1.5 tabular-nums text-text3">{en(r.callVol)}</td>
                <td className="py-1.5 tabular-nums text-text2">{r.putPts.toFixed(1)}</td>
                <td className="py-1.5 tabular-nums text-text3">{r.putDelta.toFixed(2)}</td>
                <td className="py-1.5 tabular-nums text-text3">{en(r.putVol)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── real: conditional win-rate (from decision.ranking) ─────────────
function CondBar({ wr, color }: { wr: number; color: string }) {
  const pct = Math.round(wr * 100);
  return (
    <div className="relative h-3.5 overflow-hidden rounded bg-surface2">
      <div className="h-full" style={{ width: `${pct}%`, background: color }} />
      <div className="absolute inset-y-0 left-1/2 w-px bg-border2" />
    </div>
  );
}

function CondWinRate({ rows, n }: { rows: { name: string; global: number; similar: number }[]; n: number }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 text-xs">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--color-text3)" }} />
          <span className="text-text2">כלל ההיסטוריה</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--color-accent2)" }} />
          <span className="text-text2">מקרים דומים (n={n})</span>
        </span>
      </div>
      <div className="space-y-3">
        {rows.map((c) => (
          <div key={c.name} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-text2">{c.name}</span>
              <span className="flex gap-3 tabular-nums">
                <span className="text-text3">{Math.round(c.global * 100)}%</span>
                <span className="text-accent2">{Math.round(c.similar * 100)}%</span>
              </span>
            </div>
            <CondBar wr={c.global} color="var(--color-text3)" />
            <CondBar wr={c.similar} color="var(--color-accent2)" />
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── View ───────────────────────────────────────────────────────────
export function UpcomingView({
  chains,
  decision,
}: {
  chains: OptionChain[];
  decision: CurrentDecision | null;
}) {
  const [exp, setExp] = useState(chains[0]?.expiryIso ?? "");

  const chain = chains.find((c) => c.expiryIso === exp) ?? chains[0];

  // strikes אמיתיים סביב ה-ATM — נחשב מחדש client-side לכל פקיעה נבחרת
  const strategies = useMemo(
    () => (chain && chain.atmStrike != null ? strategyBuilder(chain.atmStrike, chain.rows) : null),
    [chain],
  );

  if (chains.length === 0 || !chain) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">פקיעה קרובה</h1>
        <Empty title="אין נתוני שרשרת אופציות לפקיעות הקרובות" />
      </div>
    );
  }

  const straddle =
    chain.atmCallPts != null && chain.atmPutPts != null ? chain.atmCallPts + chain.atmPutPts : null;
  const chartAtm = chain.atmStrike ?? (chain.indexEstimate != null ? Math.round(chain.indexEstimate) : 0);

  // decision-driven historical context
  const nSim = decision?.nSimilar ?? null;
  const top = decision?.ranking.find((r) => r.rank === 1) ?? decision?.ranking[0] ?? null;
  const condRows =
    decision?.ranking.map((r) => ({ name: r.strategy, global: r.globalWr ?? 0, similar: r.condWr ?? 0 })) ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">פקיעה קרובה</h1>
        <p className="mt-1 text-sm text-text2">
          ניתוח שרשרת Put/Call מהבורסה + המלצות אסטרטגיות לפקיעה הקרובה.
        </p>
      </div>

      {/* source / expiry */}
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <label className="text-xs text-text3">פקיעה</label>
            <select
              value={exp}
              onChange={(e) => setExp(e.target.value)}
              className="rounded-lg border border-border bg-surface2 px-3 py-1.5 text-sm text-text1 outline-none focus:border-accent/50"
            >
              {chains.map((c) => (
                <option key={c.expiryIso} value={c.expiryIso}>
                  {c.expiry}{c.expiryType ? ` — ${c.expiryType}` : ""} ({c.rows.length} סטרייקים)
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-text2">מקור: Supabase · עודכן {chain.asOf}</span>
            <button className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface2 px-3 py-1.5 text-xs text-text2 transition hover:text-text1">
              <Refresh className="text-sm" /> רענן
            </button>
          </div>
        </div>
      </Panel>

      {/* ATM market state */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">מצב השוק — ATM</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Kpi label="מדד (משוערך)" value={chain.indexEstimate != null ? chain.indexEstimate.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : "—"} />
          <Kpi label="ATM Strike" value={chain.atmStrike != null ? en(chain.atmStrike) : "—"} tone="text-accent" />
          <Kpi label="Call ATM" value={chain.atmCallPts != null ? `${chain.atmCallPts.toFixed(1)} נק'` : "—"} tone="text-pos" />
          <Kpi label="Put ATM" value={chain.atmPutPts != null ? `${chain.atmPutPts.toFixed(1)} נק'` : "—"} tone="text-neg" />
          <Kpi label="Straddle" value={straddle != null ? `${straddle.toFixed(1)} נק'` : "—"} />
        </div>
      </div>

      {/* strategy recommendations (REAL — strategyBuilder around ATM) */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">
          המלצות אסטרטגיות <span className="text-sm font-normal text-text3">· סטרייקים סביב ATM {chain.atmStrike != null ? en(chain.atmStrike) : "—"}</span>
        </h2>
        {strategies ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {[1, 2, 3, 4, 5, 6].map((id) => (
              <RecoCard key={id} id={id} s={strategies[id]} />
            ))}
          </div>
        ) : (
          <Empty title="לא ניתן לחשב סטרייקים" hint="אין ATM תקין לשרשרת זו." />
        )}
      </div>

      {/* Section 5: option chain (REAL) */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">
          שרשרת אופציות — Call מול Put לפי סטרייק
        </h2>
        <Panel>
          <ChainChart
            data={chain.rows.map((r) => ({ strike: r.strike, call: r.callPts, put: r.putPts }))}
            atm={chartAtm}
            index={chain.indexEstimate ?? chartAtm}
          />
          <div className="mt-2 text-center text-xs text-text3">
            ציר אופקי: מחיר מימוש (Strike) · ציר אנכי: מחיר בנקודות
          </div>
          <details className="mt-3">
            <summary className="cursor-pointer list-none rounded-lg px-3 py-2 text-sm text-text2 transition hover:bg-surface2 hover:text-text1">
              📋 טבלת שרשרת מפורטת
            </summary>
            <div className="mt-2">
              <ChainTable rows={chain.rows} atmStrike={chain.atmStrike} />
            </div>
          </details>
        </Panel>
      </div>

      {/* Section 6: historical context (REAL — from decision engine) */}
      <div className="space-y-5">
        <h2 className="text-lg font-bold tracking-tight">ניתוח הקשר היסטורי</h2>

        {decision == null ? (
          <Empty title="אין החלטת מנוע מתועדת" hint="ההקשר ההיסטורי מגיע ממנוע ההחלטה." />
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi label="מקרים דומים" value={nSim != null ? String(nSim) : "—"} />
              <Kpi label="פקיעה קרובה" value={`${decision.expiry}${decision.expiryType ? ` (${decision.expiryType})` : ""}`} />
              <Kpi
                label="משטר תנודתיות"
                value={<span className={regimeInfo(decision.regime).tone}>{regimeInfo(decision.regime).label}</span>}
              />
              <Kpi label="ציון סיכון" value={decision.riskScore != null ? `${decision.riskScore.toFixed(1)}/10` : "—"} tone="text-warn" />
            </div>

            <div className="grid gap-5 lg:grid-cols-[2fr_3fr]">
              <Panel title="מקרים היסטוריים דומים">
                <Empty
                  title={`${nSim ?? "—"} מקרים דומים`}
                  hint="רשימת המקרים המפורטת — חישוב מלא במנוע Python (טרם נחשף ל-web)."
                />
              </Panel>
              <Panel title="Win Rate מותנה לעומת כלל ההיסטוריה">
                {condRows.length ? (
                  <CondWinRate rows={condRows} n={nSim ?? 0} />
                ) : (
                  <p className="text-sm text-text3">אין נתוני דירוג בהחלטה זו.</p>
                )}
              </Panel>
            </div>

            {top && (
              <div>
                <h3 className="mb-2 text-base font-bold tracking-tight">
                  💡 המלצה — בהתחשב בהיסטוריה ובהקשר הנוכחי
                </h3>
                <div className="rounded-2xl border border-pos/35 bg-pos/5 p-5">
                  <div className="text-sm text-text2">
                    האסטרטגיה המומלצת על בסיס <b className="text-text1">{nSim ?? "—"} מקרים דומים</b>:
                  </div>
                  <div className="mt-1 text-xl font-extrabold text-pos">{top.strategy}</div>
                  <div className="mt-1 text-sm text-text2">
                    Win Rate מותנה:{" "}
                    <b className="tabular-nums text-pos">{top.condWr != null ? `${Math.round(top.condWr * 100)}%` : "—"}</b>
                    {top.deltaWr != null && (
                      <> · {top.deltaWr >= 0 ? "▲" : "▼"} {Math.abs(top.deltaWr * 100).toFixed(1)}% מהממוצע הכולל</>
                    )}
                    {decision.riskScore != null && <> · ציון סיכון: <b className="text-text1">{decision.riskScore.toFixed(1)}/10</b></>}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <Disclaimer>
        מידע למחקר וניתוח בלבד. הסטרייקים והמלצות הם הצעה תיאורטית מבוססת פרמטרים
        סטנדרטיים — אינם המלצת מסחר. ערכי P&amp;L הם אומדן גס ואינם כוללים עמלות,
        רוחב ספרד או סיכון נוסף. מסחר באופציות כרוך בסיכון של אובדן מלא.
      </Disclaimer>
    </div>
  );
}
