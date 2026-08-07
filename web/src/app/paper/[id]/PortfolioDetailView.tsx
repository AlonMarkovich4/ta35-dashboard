"use client";

import Link from "next/link";
import { useState } from "react";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { FilterRow } from "@/components/ui/FilterRow";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { TrackRecord } from "@/components/paper/TrackRecord";
import { ArrowLeft, Trending, BarChart } from "@/components/icons";
import { en, money, pnlTone, signedPctFrac } from "@/lib/format";
import type { PortfolioDetail, LegData, EquityPoint, TrackRowData } from "@/lib/data";

// open/closed → עברית; כל סטטוס אחר מוצג כמו-שהוא (fallback).
const STATUS_MAP: Record<string, { label: string; tone: string }> = {
  open: { label: "פתוח", tone: "text-accent2" },
  closed: { label: "סגור", tone: "text-text2" },
};
const statusInfo = (s: string) => STATUS_MAP[s] ?? { label: s || "—", tone: "text-text3" };

function LegsTable({ legs }: { legs: LegData[] }) {
  if (!legs.length) return <p className="text-xs text-text3">אין פירוט רגליים לעסקה זו.</p>;
  // מחיר לא ידוע → "—". עסקאות שנפתחו לפני שמחירי הרגליים נשמרו אינן ניתנות לשחזור.
  const noPrices = legs.every((l) => l.pts === null && l.nis === null);
  return (
    <>
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
            <td className={`py-1 tabular-nums ${lg.pts === null ? "text-text3" : "text-text2"}`}>
              {lg.pts === null ? "—" : lg.pts.toFixed(1)}
            </td>
            <td className={`py-1 tabular-nums ${lg.nis === null ? "text-text3" : "text-text2"}`}>
              {lg.nis === null ? "—" : `₪${en(lg.nis)}`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    {noPrices && (
      <p className="mt-2 text-xs text-text3">
        מחירי הרגליים לא נשמרו בעסקה זו (נפתחה לפני שהמחירים נשמרו) ואינם ניתנים לשחזור —
        שרשרת האופציות ההיסטורית נדרסת בכל עדכון. עסקאות חדשות נשמרות עם מחיר לכל רגל.
      </p>
    )}
    </>
  );
}

export function PortfolioDetailView({
  detail,
  equity,
  track,
}: {
  detail: PortfolioDetail;
  equity: { points: EquityPoint[]; initial: number };
  track: TrackRowData[];
}) {
  // אפשרויות סינון נגזרות מהסטטוסים שקיימים בפועל בעסקאות התיק.
  const statuses = Array.from(new Set(detail.trades.map((t) => t.status).filter(Boolean)));
  const statusOpts = [
    { v: "all", l: "הכל" },
    ...statuses.map((s) => ({ v: s, l: statusInfo(s).label })),
  ];
  const [statusF, setStatusF] = useState<string>("all");

  const expiries = Array.from(new Set(detail.trades.map((t) => t.expiry)));
  const [expiry, setExpiry] = useState(expiries[expiries.length - 1] ?? "");

  // תשואה = ממומשת בלבד (עסקאות סגורות). פוזיציה פתוחה — ובפרט הפרמיה שנגבתה
  // עליה — אינה רווח עד שהעסקה נסגרת, ולכן מוצגת בכרטיס נפרד וללא צבע P&L.
  const pnl = detail.current - detail.initial;
  const pnlPct = detail.initial > 0 ? (pnl / detail.initial) * 100 : 0;
  const winRate = detail.closed > 0 ? Math.round((detail.wins / detail.closed) * 100) : 0;
  const exp = detail.exposure;

  const filtered = statusF === "all" ? detail.trades : detail.trades.filter((t) => t.status === statusF);
  const dayTrades = detail.trades.filter((t) => t.expiry === expiry);

  return (
    <div className="space-y-6">
      <Link href="/paper" className="inline-flex items-center gap-1.5 text-sm text-text2 transition hover:text-text1">
        <ArrowLeft className="text-base" /> חזרה לרשת התיקים
      </Link>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">{detail.name}</h1>
        <p className="mt-1 text-sm text-text2">אסטרטגיות התיק: {detail.strategies}</p>
      </div>

      <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-sm">
        <span className="font-bold text-warn">כלי מחקר בלבד — לא ייעוץ השקעות</span>
        <span className="text-text2"> — כל הנתונים הם סימולציה היסטורית בלבד.</span>
      </div>

      {/* summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Kpi label="שווי ממומש" value={`₪${en(detail.current)}`} sub="הון התחלתי + עסקאות סגורות" />
        <Kpi
          label="תשואה ממומשת"
          value={money(pnl)}
          tone={pnlTone(pnl)}
          sub={`${pnl > 0 ? "+" : ""}${pnlPct.toFixed(1)}% — ${detail.closed} עסקאות סגורות`}
          subTone={pnlTone(pnl)}
        />
        <Kpi
          label="פוזיציות פתוחות"
          value={String(exp.count)}
          sub={
            exp.count === 0
              ? "אין חשיפה פתוחה"
              : exp.cashFlow >= 0
                ? `פרמיה שנגבתה: ₪${en(exp.cashFlow)} — טרם מומשה`
                : `עלות ששולמה: ₪${en(-exp.cashFlow)} — טרם מומשה`
          }
        />
        <Kpi label="עסקאות סה״כ" value={String(detail.total)} sub={`${detail.closed} סגורות · ${exp.count} פתוחות`} />
        <Kpi label="Win Rate בפועל" value={`${winRate}%`} sub={`${detail.wins} מתוך ${detail.closed} סגורות`} />
        <Kpi label="עמלה לרגל" value={`₪${detail.commission.toFixed(1)}`} />
      </div>

      {exp.count > 0 && (
        <p className="rounded-xl border border-border bg-surface2/40 px-4 py-3 text-xs text-text2">
          <span className="font-semibold text-text1">התשואה מציגה עסקאות סגורות בלבד.</span>{" "}
          {exp.count} פוזיציות עדיין פתוחות
          {exp.cashFlow > 0 && <> והפרמיה שנגבתה עליהן (₪{en(exp.cashFlow)}) אינה רווח — היא התחייבות פתוחה</>}
          {exp.atRisk > 0 && <>, עם הפסד תיאורטי מרבי של ₪{en(exp.atRisk)}</>}
          . התוצאה שלהן תיכנס לתשואה רק בפקיעה.
        </p>
      )}

      {/* equity */}
      <Panel title={<span className="flex items-center gap-2"><Trending className="text-pos" /> עקומת שווי התיק (ממומש)</span>}>
        {equity.points.length ? (
          <EquityCurve points={equity.points} initial={equity.initial} />
        ) : (
          <p className="text-sm text-text3">אין עדיין עסקאות סגורות לבניית עקומה.</p>
        )}
      </Panel>

      {/* trades table */}
      <Panel title="עסקאות">
        <div className="mb-4">
          <FilterRow options={statusOpts} value={statusF} onPick={setStatusF} />
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
                {/* לא PnL% — האחוז הזה הוא pnl/|max_loss|, כלומר תשואה על ההון
                    בסיכון. הכותרת הישנה לצד המספר הזה קראה כמו תשואה על העלות,
                    וזה מטעה בקרדיט ספרד שבו העלות היא זיכוי. */}
                <th className="pb-2 font-medium">תשואה על הון</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => {
                const si = statusInfo(t.status);
                return (
                  <tr key={i} className="border-t border-border">
                    <td className="py-2.5 font-medium text-text1">{t.strat}</td>
                    <td className="py-2.5 tabular-nums text-text2">{t.expiry}</td>
                    <td className={`py-2.5 ${si.tone}`}>{si.label}</td>
                    <td className="py-2.5 tabular-nums text-text2">₪{en(t.entry)}</td>
                    <td className="py-2.5 tabular-nums text-text2">₪{t.comm.toFixed(1)}</td>
                    <td className={`py-2.5 tabular-nums font-semibold ${t.pnl == null ? "text-text3" : pnlTone(t.pnl)}`} dir="ltr">
                      {t.pnl == null ? "—" : money(t.pnl)}
                    </td>
                    <td className={`py-2.5 tabular-nums ${t.ror == null ? "text-text3" : pnlTone(t.ror)}`} dir="ltr">
                      {t.ror == null ? "—" : signedPctFrac(t.ror)}
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr className="border-t border-border">
                  <td colSpan={7} className="py-4 text-center text-text3">אין עסקאות בסטטוס זה</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* expiry breakdown */}
      <Panel title="פירוט לפי פקיעה">
        {expiries.length === 0 ? (
          <p className="text-sm text-text3">אין עסקאות בתיק זה.</p>
        ) : (
          <>
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
              {dayTrades.map((t, i) => {
                const si = statusInfo(t.status);
                return (
                  <div key={i} className="rounded-xl border border-border bg-surface2/40 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <span className="font-semibold text-text1">{t.strat}</span>
                      <span className={`text-sm ${si.tone}`}>{si.label}</span>
                    </div>
                    <LegsTable legs={t.legs} />
                    <div className="mt-3 rounded-lg border border-border px-3 py-2 text-xs text-text3">
                      מבנה רגליים + Payoff Diagram — ייבנו בהמשך
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </Panel>

      {/* track record */}
      <Panel title={<span className="flex items-center gap-2"><BarChart className="text-accent" /> Track Record לפי אסטרטגיה</span>}>
        <TrackRecord records={track} />
      </Panel>

      <Disclaimer>כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.</Disclaimer>
    </div>
  );
}
