"use client";

import { useState } from "react";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { Refresh } from "@/components/icons";
import { StrategyCard, type Strategy } from "@/components/options/StrategyCard";
import { ChainChart } from "@/components/charts/ChainChart";
import { Disclaimer } from "@/components/ui/Disclaimer";

// ─── Mock (נאמן-צורה; יוחלף ב-Supabase בשלב 4) ──────────────────────
const ATM = { indexEstimate: "2,087.4", strike: "2,090", callPts: "31.5", putPts: "34.2", straddle: "65.7" };

const EXPIRIES = [
  { v: "2026-07-02", l: "02/07/2026 — שבועי (41 סטרייקים)" },
  { v: "2026-07-30", l: "30/07/2026 — חודשי (53 סטרייקים)" },
];

const STRATS: Strategy[] = [
  {
    id: 1, name: "Bull Call Spread", emoji: "📈", tone: "text-pos", wr: 0.52,
    status: "profit_zone", entryNis: 950, maxProfitNis: 550, maxLossNis: 950,
    breakevens: [2105], bePct: "+0.7% מהמדד הנוכחי", riskReward: 0.58, yNowNis: 120,
    legs: [
      { action: "קנייה", type: "Call", strike: 2090, pricePts: 31.5, priceNis: 1575 },
      { action: "מכירה", type: "Call", strike: 2120, pricePts: 16.5, priceNis: 825 },
    ],
  },
  {
    id: 2, name: "Short Iron Condor", emoji: "🦅", tone: "text-accent2", wr: 0.73,
    status: "near_breakeven", entryNis: -1200, maxProfitNis: 1200, maxLossNis: 1800,
    breakevens: [2048, 2132], bePct: "±2.0% מהמדד הנוכחי", riskReward: 0.67, yNowNis: 300,
    legs: [
      { action: "מכירה", type: "Put", strike: 2050, pricePts: 18.0, priceNis: 900 },
      { action: "קנייה", type: "Put", strike: 2010, pricePts: 9.0, priceNis: 450 },
      { action: "מכירה", type: "Call", strike: 2130, pricePts: 14.0, priceNis: 700 },
      { action: "קנייה", type: "Call", strike: 2170, pricePts: 6.0, priceNis: 300 },
    ],
  },
  {
    id: 3, name: "Long Call Butterfly", emoji: "🦋", tone: "text-purple", wr: 0.58,
    status: "loss_zone", entryNis: 420, maxProfitNis: 1580, maxLossNis: 420,
    breakevens: [2069, 2111], bePct: "±1.0% מהמדד הנוכחי", riskReward: 3.76, yNowNis: -180,
    legs: [
      { action: "קנייה", type: "Call", strike: 2070, pricePts: 42.0, priceNis: 2100 },
      { action: "מכירה×2", type: "Call", strike: 2090, pricePts: 31.5, priceNis: -3150 },
      { action: "קנייה", type: "Call", strike: 2110, pricePts: 22.5, priceNis: 1125 },
    ],
  },
  {
    id: 4, name: "Long Put Butterfly", emoji: "🦋", tone: "text-purple", wr: 0.56,
    status: "near_breakeven", entryNis: 400, maxProfitNis: 1600, maxLossNis: 400,
    breakevens: [2069, 2111], bePct: "±1.0% מהמדד הנוכחי", riskReward: 4.0, yNowNis: -120,
    legs: [
      { action: "קנייה", type: "Put", strike: 2110, pricePts: 40.0, priceNis: 2000 },
      { action: "מכירה×2", type: "Put", strike: 2090, pricePts: 30.0, priceNis: -3000 },
      { action: "קנייה", type: "Put", strike: 2070, pricePts: 22.0, priceNis: 1100 },
    ],
  },
  {
    id: 5, name: "Long Straddle", emoji: "⚡", tone: "text-warn", wr: 0.62,
    status: "profit_zone", entryNis: 3285, maxProfitNis: null, maxLossNis: 3285,
    breakevens: [2024, 2156], bePct: "±1.6% מהמדד הנוכחי", riskReward: null, yNowNis: 90,
    legs: [
      { action: "קנייה", type: "Call", strike: 2090, pricePts: 31.5, priceNis: 1575 },
      { action: "קנייה", type: "Put", strike: 2090, pricePts: 34.2, priceNis: 1710 },
    ],
  },
  {
    id: 6, name: "Long Strangle", emoji: "🌪️", tone: "text-neg", wr: 0.47,
    status: "loss_zone", entryNis: 2100, maxProfitNis: null, maxLossNis: 2100,
    breakevens: [2010, 2170], bePct: "±2.7% מהמדד הנוכחי", riskReward: null, yNowNis: -240,
    legs: [
      { action: "קנייה", type: "Call", strike: 2120, pricePts: 22.0, priceNis: 1100 },
      { action: "קנייה", type: "Put", strike: 2060, pricePts: 20.0, priceNis: 1000 },
    ],
  },
];

// ─── Section 5 mock ─────────────────────────────────────────────────
const CHAIN = [
  { strike: 1990, call: 108, put: 6, callDelta: 0.92, putDelta: -0.08, callVol: 120, putVol: 1840 },
  { strike: 2010, call: 92, put: 9, callDelta: 0.87, putDelta: -0.13, callVol: 210, putVol: 1620 },
  { strike: 2030, call: 76, put: 13, callDelta: 0.8, putDelta: -0.2, callVol: 340, putVol: 1450 },
  { strike: 2050, call: 60, put: 19, callDelta: 0.71, putDelta: -0.29, callVol: 560, putVol: 1180 },
  { strike: 2070, call: 45, put: 27, callDelta: 0.6, putDelta: -0.4, callVol: 880, putVol: 960 },
  { strike: 2090, call: 31.5, put: 34.2, callDelta: 0.5, putDelta: -0.5, callVol: 1240, putVol: 1210 },
  { strike: 2110, call: 22.5, put: 45, callDelta: 0.39, putDelta: -0.61, callVol: 990, putVol: 720 },
  { strike: 2130, call: 14, put: 58, callDelta: 0.29, putDelta: -0.71, callVol: 760, putVol: 480 },
  { strike: 2150, call: 9, put: 74, callDelta: 0.2, putDelta: -0.8, callVol: 430, putVol: 290 },
  { strike: 2170, call: 6, put: 92, callDelta: 0.13, putDelta: -0.87, callVol: 250, putVol: 160 },
  { strike: 2190, call: 4, put: 110, callDelta: 0.08, putDelta: -0.92, callVol: 140, putVol: 90 },
];

// ─── Section 6 mock ─────────────────────────────────────────────────
const N_SIM = 12;
const SIMILAR = [
  { date: "28/06/2024", type: "W", move: 0.91 },
  { date: "30/06/2023", type: "W", move: 0.62 },
  { date: "01/07/2022", type: "W", move: 1.12 },
  { date: "02/07/2021", type: "W", move: 0.48 },
  { date: "26/06/2020", type: "W", move: -0.73 },
  { date: "28/06/2019", type: "W", move: 0.55 },
  { date: "29/06/2018", type: "W", move: 0.83 },
  { date: "30/06/2017", type: "W", move: 0.39 },
];
const COND = [
  { name: "Bull Call Spread", global: 0.52, similar: 0.5 },
  { name: "Short Iron Condor", global: 0.73, similar: 0.78 },
  { name: "Long Call Butterfly", global: 0.58, similar: 0.61 },
  { name: "Long Put Butterfly", global: 0.56, similar: 0.59 },
  { name: "Long Straddle", global: 0.62, similar: 0.55 },
  { name: "Long Strangle", global: 0.47, similar: 0.42 },
];

const enc = (n: number) => n.toLocaleString("en-US");

function ChainTable() {
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
          {CHAIN.map((r) => {
            const atmRow = r.strike === 2090;
            return (
              <tr
                key={r.strike}
                className={`border-t border-border ${atmRow ? "bg-pos/10" : ""}`}
              >
                <td className={`py-1.5 tabular-nums ${atmRow ? "font-bold text-pos" : "text-text1"}`}>
                  {enc(r.strike)}
                </td>
                <td className="py-1.5 tabular-nums text-text2">{r.call.toFixed(1)}</td>
                <td className="py-1.5 tabular-nums text-text3">{r.callDelta.toFixed(2)}</td>
                <td className="py-1.5 tabular-nums text-text3">{enc(r.callVol)}</td>
                <td className="py-1.5 tabular-nums text-text2">{r.put.toFixed(1)}</td>
                <td className="py-1.5 tabular-nums text-text3">{r.putDelta.toFixed(2)}</td>
                <td className="py-1.5 tabular-nums text-text3">{enc(r.putVol)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SimilarTable() {
  return (
    <div>
      <table className="w-full text-right text-sm">
        <thead>
          <tr className="text-xs text-text3">
            <th className="pb-2 font-medium">תאריך</th>
            <th className="pb-2 font-medium">סוג</th>
            <th className="pb-2 font-medium">תנועה (%)</th>
          </tr>
        </thead>
        <tbody>
          {SIMILAR.map((r) => (
            <tr key={r.date} className="border-t border-border">
              <td className="py-2 tabular-nums text-text2">{r.date}</td>
              <td className="py-2 text-text2">{r.type}</td>
              <td className={`py-2 tabular-nums font-semibold ${r.move >= 0 ? "text-pos" : "text-neg"}`} dir="ltr">
                {r.move >= 0 ? "+" : ""}
                {r.move.toFixed(2)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 text-xs text-text3">מוצגים {SIMILAR.length} מתוך {N_SIM} מקרים</div>
    </div>
  );
}

function CondBar({ wr, color }: { wr: number; color: string }) {
  const pct = Math.round(wr * 100);
  return (
    <div className="relative h-3.5 overflow-hidden rounded bg-surface2">
      <div className="h-full" style={{ width: `${pct}%`, background: color }} />
      <div className="absolute inset-y-0 left-1/2 w-px bg-border2" />
    </div>
  );
}

function CondWinRate() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 text-xs">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--color-text3)" }} />
          <span className="text-text2">כלל ההיסטוריה</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--color-accent2)" }} />
          <span className="text-text2">מקרים דומים (n={N_SIM})</span>
        </span>
      </div>
      <div className="space-y-3">
        {COND.map((c) => (
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

export default function UpcomingPage() {
  const [exp, setExp] = useState(EXPIRIES[0].v);
  const [tol, setTol] = useState(0.5);

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
              {EXPIRIES.map((o) => (
                <option key={o.v} value={o.v}>
                  {o.l}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-text2">מקור: Supabase · עודכן 14:05</span>
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
          <Kpi label="מדד (משוערך)" value={ATM.indexEstimate} />
          <Kpi label="ATM Strike" value={ATM.strike} tone="text-accent" />
          <Kpi label="Call ATM" value={`${ATM.callPts} נק'`} tone="text-pos" />
          <Kpi label="Put ATM" value={`${ATM.putPts} נק'`} tone="text-neg" />
          <Kpi label="Straddle" value={`${ATM.straddle} נק'`} />
        </div>
      </div>

      {/* strategy recommendations */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">המלצות אסטרטגיות</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          {STRATS.map((s) => (
            <StrategyCard key={s.id} s={s} />
          ))}
        </div>
      </div>

      {/* Section 5: option chain */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">
          שרשרת אופציות — Call מול Put לפי סטרייק
        </h2>
        <Panel>
          <ChainChart data={CHAIN} atm={2090} index={2087.4} />
          <div className="mt-2 text-center text-xs text-text3">
            ציר אופקי: מחיר מימוש (Strike) · ציר אנכי: מחיר בנקודות
          </div>
          <details className="mt-3">
            <summary className="cursor-pointer list-none rounded-lg px-3 py-2 text-sm text-text2 transition hover:bg-surface2 hover:text-text1">
              📋 טבלת שרשרת מפורטת
            </summary>
            <div className="mt-2">
              <ChainTable />
            </div>
          </details>
        </Panel>
      </div>

      {/* Section 6: historical context */}
      <div className="space-y-5">
        <h2 className="text-lg font-bold tracking-tight">ניתוח הקשר היסטורי</h2>

        <Panel>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <label className="text-xs text-text3">סבילות תנועה (±%)</label>
              <input
                type="range"
                min={0.5}
                max={2.5}
                step={0.5}
                value={tol}
                onChange={(e) => setTol(parseFloat(e.target.value))}
                className="accent-[var(--color-accent)]"
              />
              <span className="text-xs font-semibold tabular-nums text-text1">±{tol}%</span>
            </div>
            <div className="text-xs text-text2">
              סוג: <b className="text-text1">שבועי</b> · חודש:{" "}
              <b className="text-text1">יולי</b> · תנועה קודמת:{" "}
              <b className="text-text1">+0.85%</b> ±{tol}%
            </div>
          </div>
        </Panel>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi label="מקרים דומים" value={String(N_SIM)} />
          <Kpi label="פקיעה קרובה" value="02/07/2026" />
          <Kpi label="תנועה אחרונה" value="+0.85%" tone="text-pos" />
          <Kpi label="ציון סיכון" value="4.2/10" tone="text-warn" sub="בינוני" />
        </div>

        <div className="grid gap-5 lg:grid-cols-[2fr_3fr]">
          <Panel title="מקרים היסטוריים דומים">
            <SimilarTable />
          </Panel>
          <Panel title="Win Rate מותנה לעומת כלל ההיסטוריה">
            <CondWinRate />
          </Panel>
        </div>

        <div className="rounded-xl border border-warn/25 bg-warn/5 px-4 py-3 text-sm text-text2">
          📌 <b className="text-text1">אירועים בחלון 7 ימים:</b> החלטת ריבית בנק ישראל
          · פקיעת חוזים בארה״ב
        </div>

        <div>
          <h3 className="mb-2 text-base font-bold tracking-tight">
            💡 המלצה — בהתחשב בהיסטוריה ובהקשר הנוכחי
          </h3>
          <div className="rounded-2xl border border-pos/35 bg-pos/5 p-5">
            <div className="text-sm text-text2">
              האסטרטגיה המומלצת על בסיס{" "}
              <b className="text-text1">{N_SIM} מקרים דומים</b>:
            </div>
            <div className="mt-1 text-xl font-extrabold text-pos">Short Iron Condor</div>
            <div className="mt-1 text-sm text-text2">
              Win Rate מותנה:{" "}
              <b className="tabular-nums text-pos">78%</b> · ▲ 5.0% מהממוצע הכולל ·
              ציון סיכון: <b className="text-text1">4.2/10</b>
            </div>
          </div>
        </div>
      </div>

      <Disclaimer>
        מידע למחקר וניתוח בלבד. הסטרייקים והמלצות הם הצעה תיאורטית מבוססת פרמטרים
        סטנדרטיים — אינם המלצת מסחר. ערכי P&amp;L הם אומדן גס ואינם כוללים עמלות,
        רוחב ספרד או סיכון נוסף. מסחר באופציות כרוך בסיכון של אובדן מלא.
      </Disclaimer>
    </div>
  );
}
