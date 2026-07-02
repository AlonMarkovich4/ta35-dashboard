"use client";

import Link from "next/link";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { Card } from "@/components/ui/Card";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { card } from "@/lib/ui";
import { en, money, pnlTone } from "@/lib/format";
import { Wallet, Trending, BarChart, Bell, Wrench, Plus } from "@/components/icons";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { TrackRecord } from "@/components/paper/TrackRecord";
import type {
  PortfolioCardData,
  ClosedSummary,
  EquityPoint,
  TrackRowData,
} from "@/lib/data";

function Row({ k, v, cls = "text-text1" }: { k: string; v: React.ReactNode; cls?: string }) {
  return (
    <div className="flex items-center justify-between py-0.5 text-sm">
      <span className="text-text3">{k}</span>
      <span className={cls}>{v}</span>
    </div>
  );
}

function PortfolioCard({ p }: { p: PortfolioCardData }) {
  const pnl = p.current - p.initial;
  const pnlPct = p.initial > 0 ? (pnl / p.initial) * 100 : 0;
  const tone = pnlTone(pnl);
  return (
    <Card className="border-t-2 border-t-accent/50 p-5">
      <div className="mb-3 text-base font-bold text-text1">{p.name}</div>
      <Row k="שווי נוכחי" v={`₪${en(p.current)}`} cls="font-semibold text-text1" />
      <Row k="שווי התחלתי" v={`₪${en(p.initial)}`} cls="text-text2" />
      <Row k="תשואה" v={`${money(pnl)} (${pnl > 0 ? "+" : ""}${pnlPct.toFixed(1)}%)`} cls={`font-bold ${tone}`} />
      <Row k="עסקאות פתוחות / סגורות" v={`${p.open} / ${p.closed}`} cls="text-text2" />
      <Row k="עמלה לרגל" v={`₪${p.commission.toFixed(1)}`} cls="text-text2" />
      <div className="mt-2 text-sm">
        <div className="text-text3">אסטרטגיות</div>
        <div className="mt-0.5 text-xs text-text2">{p.strategies}</div>
      </div>
      <Link href={`/paper/${p.id}`}
        className="mt-4 block rounded-lg border border-accent/40 bg-accent/10 py-2 text-center text-sm font-semibold text-accent transition hover:bg-accent/20">
        פתח →
      </Link>
    </Card>
  );
}

export function PaperView({
  portfolios,
  summary,
  equity,
  track,
}: {
  portfolios: PortfolioCardData[];
  summary: ClosedSummary;
  equity: { points: EquityPoint[]; initial: number };
  track: TrackRowData[];
}) {
  const totalPnl = summary.totalPnl;
  const totalTone = totalPnl >= 0 ? "text-pos" : "text-neg";
  const totalBorder = totalPnl >= 0 ? "border-t-pos/60" : "border-t-neg/60";
  const winRatePct = Math.round(summary.winRate * 100);

  return (
    <div className="space-y-6">
      <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
        <Wallet className="text-accent" /> תיקי דמו
      </h1>

      <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-sm">
        <span className="font-bold text-warn">כלי מחקר בלבד — לא ייעוץ השקעות</span>
        <span className="text-text2"> — כל הנתונים הם סימולציה היסטורית בלבד.</span>
      </div>

      {/* create portfolio (visual) */}
      <details className={card}>
        <summary className="flex cursor-pointer list-none items-center gap-2 p-4 text-sm font-semibold text-text2 transition hover:text-text1">
          <Plus className="text-text3" /> צור תיק חדש
        </summary>
        <div className="border-t border-border p-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <input placeholder="שם התיק" className="rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text1 outline-none focus:border-accent/50" />
            <input placeholder="הון התחלתי (₪)" defaultValue="100000" className="rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text1 outline-none focus:border-accent/50" />
            <input placeholder="עמלה לרגל (₪)" defaultValue="2.5" className="rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text1 outline-none focus:border-accent/50" />
          </div>
          <button className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent">
            <Plus /> צור תיק
          </button>
          <p className="mt-2 text-xs text-text3">יצירת תיק כותבת ל-DB — תחובר ל-backend בהמשך.</p>
        </div>
      </details>

      {/* portfolio grid */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">תיקים פעילים ({portfolios.length})</h2>
        {portfolios.length === 0 ? (
          <p className="text-sm text-text3">אין תיקים פעילים.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {portfolios.map((p) => <PortfolioCard key={p.id} p={p} />)}
          </div>
        )}
      </div>

      {/* aggregate performance */}
      <div className="space-y-4">
        <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight">
          <Trending className="text-pos" /> ביצועים מצטברים — כל התיקים
        </h2>

        <Card className={`border-t-2 ${totalBorder} p-5 text-center`}>
          <div className="text-xs text-text3">סך רווח/הפסד נטו (כל העסקאות הסגורות)</div>
          <div className={`mt-1 text-3xl font-extrabold tabular-nums ${totalTone}`} dir="ltr">{money(totalPnl)}</div>
        </Card>

        <div className="grid gap-4 sm:grid-cols-3">
          <Kpi label="עסקאות סגורות" value={String(summary.closedCount)} />
          <Kpi label="Win Rate" value={`${winRatePct}%`} tone={summary.winRate >= 0.5 ? "text-pos" : "text-text1"}
            sub={`${summary.wins} רווחיות מתוך ${summary.closedCount}`} />
          <Kpi label="ממוצע לעסקה" value={money(summary.avgPnl)} tone={pnlTone(summary.avgPnl)} />
        </div>

        <Panel title={<span className="flex items-center gap-2"><Trending className="text-pos" /> עקומת שווי כוללת</span>}>
          {equity.points.length ? (
            <EquityCurve points={equity.points} initial={equity.initial} />
          ) : (
            <p className="text-sm text-text3">אין עדיין עסקאות סגורות לבניית עקומה.</p>
          )}
        </Panel>

        <Panel title={<span className="flex items-center gap-2"><BarChart className="text-accent" /> ביצועים לפי אסטרטגיה</span>}>
          <TrackRecord records={track} />
        </Panel>
      </div>

      {/* close matured (visual) */}
      <Panel title={<span className="flex items-center gap-2"><Bell className="text-warn" /> סגירת פקיעות שהבשילו</span>}>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-surface2 px-4 py-3">
          <span className="text-sm text-text2">פקיעה <b className="text-text1">02/07/2026</b> — עסקאות פתוחות · סטלמנט זמין</span>
          <button className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs text-text2">סגור</button>
        </div>
        <p className="mt-2 text-xs text-text3">סגירה כותבת ל-DB (בלתי-הפיכה) ודורשת אישור — תחובר בהמשך.</p>
      </Panel>

      {/* manual actions (visual) */}
      <Panel title={<span className="flex items-center gap-2"><Wrench className="text-text2" /> פעולות ידניות (בדיקה)</span>}>
        <button className="rounded-lg border border-border bg-surface2 px-4 py-2 text-sm text-text2">פתח עסקאות לפקיעות השבוע</button>
        <p className="mt-2 text-xs text-text3">פעולה ידנית לבדיקה — פותחת עסקאות בכל התיקים. תחובר בהמשך.</p>
      </Panel>

      <Disclaimer>כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.</Disclaimer>
    </div>
  );
}
