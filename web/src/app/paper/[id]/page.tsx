"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { FilterRow } from "@/components/ui/FilterRow";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { TrackRecord, type TrackRow } from "@/components/paper/TrackRecord";
import { ArrowLeft, Trending, BarChart } from "@/components/icons";
import { en, money, pnlTone } from "@/lib/format";

// ─── Mock (נאמן-צורה; יוחלף ב-Supabase בשלב 4) ──────────────────────
type Meta = {
  name: string; strategies: string; initial: number; current: number;
  commission: number; total: number; wins: number; closed: number;
};

const META: Record<number, Meta> = {
  1: { name: "תיק ראשי", strategies: "כל האסטרטגיות", initial: 100000, current: 110521, commission: 2.5, total: 54, wins: 31, closed: 48 },
  2: { name: "Iron Condor בלבד", strategies: "Short Iron Condor", initial: 100000, current: 104230, commission: 2.5, total: 23, wins: 16, closed: 22 },
  3: { name: "תנודתיות", strategies: "Long Straddle, Long Strangle", initial: 50000, current: 47180, commission: 2.5, total: 20, wins: 9, closed: 18 },
};

type Leg = { action: "קנה" | "מכור"; type: string; strike: number; qty: number; pts: number; nis: number };
type Trade = {
  strat: string; expiry: string; status: "open" | "closed" | "skipped";
  entry: number; comm: number; pnl: number | null; pnlPct: number | null; legs: Leg[];
};

const TRADES: Trade[] = [
  { strat: "Short Iron Condor", expiry: "25/06/2026", status: "closed", entry: 1200, comm: 10, pnl: 820, pnlPct: 0.068,
    legs: [
      { action: "מכור", type: "Put", strike: 2050, qty: 1, pts: 18.0, nis: 900 },
      { action: "קנה", type: "Put", strike: 2010, qty: 1, pts: 9.0, nis: 450 },
      { action: "מכור", type: "Call", strike: 2130, qty: 1, pts: 14.0, nis: 700 },
      { action: "קנה", type: "Call", strike: 2170, qty: 1, pts: 6.0, nis: 300 },
    ] },
  { strat: "Long Call Butterfly", expiry: "25/06/2026", status: "closed", entry: 420, comm: 7.5, pnl: -180, pnlPct: -0.429,
    legs: [
      { action: "קנה", type: "Call", strike: 2070, qty: 1, pts: 42.0, nis: 2100 },
      { action: "מכור", type: "Call", strike: 2090, qty: 2, pts: 31.5, nis: 3150 },
      { action: "קנה", type: "Call", strike: 2110, qty: 1, pts: 22.5, nis: 1125 },
    ] },
  { strat: "Long Straddle", expiry: "25/06/2026", status: "closed", entry: 3285, comm: 5, pnl: 540, pnlPct: 0.164,
    legs: [
      { action: "קנה", type: "Call", strike: 2090, qty: 1, pts: 31.5, nis: 1575 },
      { action: "קנה", type: "Put", strike: 2090, qty: 1, pts: 34.2, nis: 1710 },
    ] },
  { strat: "Short Iron Condor", expiry: "02/07/2026", status: "open", entry: 1180, comm: 10, pnl: null, pnlPct: null,
    legs: [
      { action: "מכור", type: "Put", strike: 2050, qty: 1, pts: 17.5, nis: 875 },
      { action: "קנה", type: "Put", strike: 2010, qty: 1, pts: 8.5, nis: 425 },
      { action: "מכור", type: "Call", strike: 2130, qty: 1, pts: 13.5, nis: 675 },
      { action: "קנה", type: "Call", strike: 2170, qty: 1, pts: 5.5, nis: 275 },
    ] },
  { strat: "Bull Call Spread", expiry: "02/07/2026", status: "open", entry: 950, comm: 5, pnl: null, pnlPct: null,
    legs: [
      { action: "קנה", type: "Call", strike: 2090, qty: 1, pts: 31.5, nis: 1575 },
      { action: "מכור", type: "Call", strike: 2120, qty: 1, pts: 16.5, nis: 825 },
    ] },
  { strat: "Long Strangle", expiry: "02/07/2026", status: "open", entry: 2100, comm: 5, pnl: null, pnlPct: null,
    legs: [
      { action: "קנה", type: "Call", strike: 2120, qty: 1, pts: 22.0, nis: 1100 },
      { action: "קנה", type: "Put", strike: 2060, qty: 1, pts: 20.0, nis: 1000 },
    ] },
];

const TRACK: TrackRow[] = [
  { name: "Short Iron Condor", total: 12, wins: 9, winRate: 0.75, totalPnl: 3200, avgPnl: 267 },
  { name: "Long Straddle", total: 8, wins: 5, winRate: 0.63, totalPnl: 1400, avgPnl: 175 },
  { name: "Long Call Butterfly", total: 6, wins: 3, winRate: 0.5, totalPnl: 320, avgPnl: 53 },
  { name: "Bull Call Spread", total: 7, wins: 3, winRate: 0.43, totalPnl: -210, avgPnl: -30 },
];

const STATUS = {
  open: { label: "פתוח", tone: "text-accent2" },
  closed: { label: "סגור", tone: "text-text2" },
  skipped: { label: "דולג", tone: "text-text3" },
} as const;

function makeCurve(initial: number, current: number) {
  const labels = ["ינו", "פבר", "מרץ", "אפר", "מאי", "יונ", "יול", "אוג", "ספט", "אוק", "נוב", "דצמ"];
  const pts = labels.map((label, i) => {
    const tt = i / (labels.length - 1);
    const base = initial + (current - initial) * tt;
    const wiggle = Math.sin(i * 1.7) * Math.abs(current - initial) * 0.12;
    return { label, value: Math.round(base + wiggle) };
  });
  pts[pts.length - 1] = { label: "דצמ", value: current };
  return pts;
}

function LegsTable({ legs }: { legs: Leg[] }) {
  return (
    <table className="w-full text-right text-xs">
      <thead>
        <tr className="text-text3">
          <th className="pb-1 font-medium">פעולה</th>
          <th className="pb-1 font-medium">סוג</th>
          <th className="pb-1 font-medium">סטרייק</th>
          <th className="pb-1 font-medium">כמות</th>
          <th className="pb-1 font-medium">מחיר נק&apos;</th>
          <th className="pb-1 font-medium">מחיר ₪</th>
        </tr>
      </thead>
      <tbody>
        {legs.map((lg, i) => (
          <tr key={i} className="border-t border-border">
            <td className={`py-1 font-semibold ${lg.action === "קנה" ? "text-pos" : "text-neg"}`}>{lg.action}</td>
            <td className="py-1 text-text2">{lg.type}</td>
            <td className="py-1 tabular-nums text-text2">{en(lg.strike)}</td>
            <td className="py-1 tabular-nums text-text2">{lg.qty}</td>
            <td className="py-1 tabular-nums text-text2">{lg.pts.toFixed(1)}</td>
            <td className="py-1 tabular-nums text-text2">₪{en(lg.nis)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const STATUS_OPTS = [
  { v: "all", l: "הכל" },
  { v: "open", l: "פתוח" },
  { v: "closed", l: "סגור" },
  { v: "skipped", l: "דולג" },
] as const;
type StatusV = (typeof STATUS_OPTS)[number]["v"];

export default function PortfolioDetailPage() {
  const params = useParams();
  const id = Number(Array.isArray(params.id) ? params.id[0] : params.id);
  const meta = META[id] ?? { ...META[1], name: `תיק #${id}` };

  const [statusF, setStatusF] = useState<StatusV>("all");
  const expiries = Array.from(new Set(TRADES.map((t) => t.expiry)));
  const [expiry, setExpiry] = useState(expiries[expiries.length - 1]);

  const pnl = meta.current - meta.initial;
  const pnlPct = meta.initial > 0 ? (pnl / meta.initial) * 100 : 0;
  const winRate = meta.closed > 0 ? Math.round((meta.wins / meta.closed) * 100) : 0;

  const filtered = statusF === "all" ? TRADES : TRADES.filter((t) => t.status === statusF);
  const dayTrades = TRADES.filter((t) => t.expiry === expiry);

  return (
    <div className="space-y-6">
      <Link href="/paper" className="inline-flex items-center gap-1.5 text-sm text-text2 transition hover:text-text1">
        <ArrowLeft className="text-base" /> חזרה לרשת התיקים
      </Link>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">{meta.name}</h1>
        <p className="mt-1 text-sm text-text2">אסטרטגיות התיק: {meta.strategies}</p>
      </div>

      <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-sm">
        <span className="font-bold text-warn">כלי מחקר בלבד — לא ייעוץ השקעות</span>
        <span className="text-text2"> — כל הנתונים הם סימולציה היסטורית בלבד.</span>
      </div>

      {/* summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi label="שווי נוכחי" value={`₪${en(meta.current)}`} />
        <Kpi label="תשואה כוללת" value={money(pnl)} tone={pnlTone(pnl)} sub={`${pnl > 0 ? "+" : ""}${pnlPct.toFixed(1)}%`} subTone={pnlTone(pnl)} />
        <Kpi label="עסקאות סה״כ" value={String(meta.total)} />
        <Kpi label="Win Rate בפועל" value={`${winRate}%`} sub={`${meta.wins} מתוך ${meta.closed} סגורות`} />
        <Kpi label="עמלה לרגל" value={`₪${meta.commission.toFixed(1)}`} />
      </div>

      {/* equity */}
      <Panel title={<span className="flex items-center gap-2"><Trending className="text-pos" /> עקומת שווי התיק</span>}>
        <EquityCurve points={makeCurve(meta.initial, meta.current)} initial={meta.initial} />
      </Panel>

      {/* trades table */}
      <Panel title="עסקאות">
        <div className="mb-4">
          <FilterRow
            options={STATUS_OPTS.map((o) => ({ v: o.v, l: o.l }))}
            value={statusF}
            onPick={(v) => setStatusF(v as StatusV)}
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-right text-sm">
            <thead>
              <tr className="text-xs text-text3">
                <th className="pb-2 font-medium">אסטרטגיה</th>
                <th className="pb-2 font-medium">פקיעה</th>
                <th className="pb-2 font-medium">סטטוס</th>
                <th className="pb-2 font-medium">עלות כניסה</th>
                <th className="pb-2 font-medium">עמלות</th>
                <th className="pb-2 font-medium">PnL</th>
                <th className="pb-2 font-medium">PnL%</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="py-2.5 font-medium text-text1">{t.strat}</td>
                  <td className="py-2.5 tabular-nums text-text2">{t.expiry}</td>
                  <td className={`py-2.5 ${STATUS[t.status].tone}`}>{STATUS[t.status].label}</td>
                  <td className="py-2.5 tabular-nums text-text2">₪{en(t.entry)}</td>
                  <td className="py-2.5 tabular-nums text-text2">₪{t.comm.toFixed(1)}</td>
                  <td className={`py-2.5 tabular-nums font-semibold ${t.pnl == null ? "text-text3" : pnlTone(t.pnl)}`} dir="ltr">
                    {t.pnl == null ? "—" : money(t.pnl)}
                  </td>
                  <td className={`py-2.5 tabular-nums ${t.pnlPct == null ? "text-text3" : pnlTone(t.pnlPct)}`} dir="ltr">
                    {t.pnlPct == null ? "—" : `${t.pnlPct > 0 ? "+" : ""}${(t.pnlPct * 100).toFixed(1)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* expiry breakdown */}
      <Panel title="פירוט לפי פקיעה">
        <div className="mb-4 flex items-center gap-3">
          <label className="text-xs text-text3">בחר פקיעה</label>
          <select
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            className="rounded-lg border border-border bg-surface2 px-3 py-1.5 text-sm text-text1 outline-none focus:border-accent/50"
          >
            {expiries.map((x) => (
              <option key={x} value={x}>{x}</option>
            ))}
          </select>
        </div>

        <div className="space-y-4">
          {dayTrades.map((t, i) => (
            <div key={i} className="rounded-xl border border-border bg-surface2/40 p-4">
              <div className="mb-3 flex items-center justify-between">
                <span className="font-semibold text-text1">{t.strat}</span>
                <span className={`text-sm ${STATUS[t.status].tone}`}>{STATUS[t.status].label}</span>
              </div>
              <LegsTable legs={t.legs} />
              <div className="mt-3 rounded-lg border border-border px-3 py-2 text-xs text-text3">
                מבנה רגליים + Payoff Diagram — ייבנו בשלב 5
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* track record */}
      <Panel title={<span className="flex items-center gap-2"><BarChart className="text-accent" /> Track Record לפי אסטרטגיה</span>}>
        <TrackRecord records={TRACK} />
      </Panel>

      <Disclaimer>כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.</Disclaimer>
    </div>
  );
}
