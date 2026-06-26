import Link from "next/link";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { TrackRecord, type TrackRow } from "@/components/paper/TrackRecord";

// ─── Mock (נאמן-צורה; יוחלף ב-Supabase בשלב 4) ──────────────────────
type Portfolio = {
  id: number; name: string; initial: number; current: number;
  open: number; closed: number; commission: number; strategies: string;
};

const PORTFOLIOS: Portfolio[] = [
  { id: 1, name: "תיק ראשי", initial: 100000, current: 110521, open: 6, closed: 48, commission: 2.5, strategies: "כל האסטרטגיות" },
  { id: 2, name: "Iron Condor בלבד", initial: 100000, current: 104230, open: 1, closed: 22, commission: 2.5, strategies: "Short Iron Condor" },
  { id: 3, name: "תנודתיות", initial: 50000, current: 47180, open: 2, closed: 18, commission: 2.5, strategies: "Long Straddle, Long Strangle" },
];

const TOTAL_INITIAL = PORTFOLIOS.reduce((s, p) => s + p.initial, 0);
const TOTAL_CURRENT = PORTFOLIOS.reduce((s, p) => s + p.current, 0);

const EQUITY = [
  { label: "ינו", value: 250000 }, { label: "פבר", value: 251800 }, { label: "מרץ", value: 250400 },
  { label: "אפר", value: 253900 }, { label: "מאי", value: 255200 }, { label: "יונ", value: 254100 },
  { label: "יול", value: 257600 }, { label: "אוג", value: 256000 }, { label: "ספט", value: 259300 },
  { label: "אוק", value: 260100 }, { label: "נוב", value: 261400 }, { label: "דצמ", value: 261931 },
];

const GLOBAL_TRACK: TrackRow[] = [
  { name: "Short Iron Condor", total: 30, wins: 22, winRate: 0.73, totalPnl: 6800, avgPnl: 227 },
  { name: "Long Call Butterfly", total: 14, wins: 8, winRate: 0.57, totalPnl: 2100, avgPnl: 150 },
  { name: "Long Put Butterfly", total: 12, wins: 7, winRate: 0.58, totalPnl: 1500, avgPnl: 125 },
  { name: "Long Straddle", total: 10, wins: 6, winRate: 0.6, totalPnl: 1200, avgPnl: 120 },
  { name: "Bull Call Spread", total: 16, wins: 8, winRate: 0.5, totalPnl: 900, avgPnl: 56 },
  { name: "Long Strangle", total: 6, wins: 2, winRate: 0.33, totalPnl: -569, avgPnl: -95 },
];

const en = (v: number) => Math.round(v).toLocaleString("en-US");
const money = (v: number) => `${v > 0 ? "+" : v < 0 ? "-" : ""}₪${en(Math.abs(v))}`;

function Row({ k, v, cls = "text-text1" }: { k: string; v: React.ReactNode; cls?: string }) {
  return (
    <div className="flex items-center justify-between py-0.5 text-sm">
      <span className="text-text3">{k}</span>
      <span className={cls}>{v}</span>
    </div>
  );
}

function PortfolioCard({ p }: { p: Portfolio }) {
  const pnl = p.current - p.initial;
  const pnlPct = p.initial > 0 ? (pnl / p.initial) * 100 : 0;
  const tone = pnl > 0 ? "text-pos" : pnl < 0 ? "text-neg" : "text-text2";
  return (
    <div className="rounded-2xl border border-border border-t-2 border-t-accent/50 bg-surface/70 p-5 backdrop-blur">
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
    </div>
  );
}

export default function PaperPage() {
  const totalPnl = TOTAL_CURRENT - TOTAL_INITIAL;
  const totalTone = totalPnl >= 0 ? "text-pos" : "text-neg";
  const totalBorder = totalPnl >= 0 ? "border-t-pos/60" : "border-t-neg/60";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">📊 תיקי דמו</h1>

      <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-sm">
        <span className="font-bold text-warn">⚠️ כלי מחקר בלבד — לא ייעוץ השקעות</span>
        <span className="text-text2"> — כל הנתונים הם סימולציה היסטורית בלבד.</span>
      </div>

      {/* create portfolio (visual) */}
      <details className="rounded-2xl border border-border bg-surface/70 backdrop-blur">
        <summary className="cursor-pointer list-none p-4 text-sm font-semibold text-text2 transition hover:text-text1">
          ➕ צור תיק חדש
        </summary>
        <div className="border-t border-border p-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <input placeholder="שם התיק" className="rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text1 outline-none" />
            <input placeholder="הון התחלתי (₪)" defaultValue="100000" className="rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text1 outline-none" />
            <input placeholder="עמלה לרגל (₪)" defaultValue="2.5" className="rounded-lg border border-border bg-surface2 px-3 py-2 text-sm text-text1 outline-none" />
          </div>
          <button className="mt-3 rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent">✅ צור תיק</button>
          <p className="mt-2 text-xs text-text3">יצירת תיק כותבת ל-DB — תחובר ל-backend בשלב 4.</p>
        </div>
      </details>

      {/* portfolio grid */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">תיקים פעילים ({PORTFOLIOS.length})</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {PORTFOLIOS.map((p) => <PortfolioCard key={p.id} p={p} />)}
        </div>
      </div>

      {/* aggregate performance */}
      <div className="space-y-4">
        <h2 className="text-lg font-bold tracking-tight">💰 ביצועים מצטברים — כל התיקים</h2>

        <div className={`rounded-2xl border border-border border-t-2 ${totalBorder} bg-surface/70 p-5 text-center backdrop-blur`}>
          <div className="text-xs text-text3">סך רווח/הפסד נטו (כל העסקאות הסגורות)</div>
          <div className={`mt-1 text-3xl font-extrabold tabular-nums ${totalTone}`} dir="ltr">{money(totalPnl)}</div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <Kpi label="עסקאות סגורות" value="88" />
          <Kpi label="Win Rate" value="64%" tone="text-pos" sub="56 רווחיות מתוך 88" />
          <Kpi label="ממוצע לעסקה" value="+₪134" tone="text-pos" />
        </div>

        <Panel title="📈 עקומת שווי כוללת">
          <EquityCurve points={EQUITY} initial={TOTAL_INITIAL} />
        </Panel>

        <Panel title="🏆 ביצועים לפי אסטרטגיה">
          <TrackRecord records={GLOBAL_TRACK} />
        </Panel>
      </div>

      {/* close matured (visual) */}
      <Panel title="🔔 סגירת פקיעות שהבשילו">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-surface2 px-4 py-3">
          <span className="text-sm text-text2">פקיעה <b className="text-text1">02/07/2026</b> — 9 עסקאות פתוחות · סטלמנט זמין</span>
          <button className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs text-text2">🔒 סגור</button>
        </div>
        <p className="mt-2 text-xs text-text3">סגירה כותבת ל-DB (בלתי-הפיכה) ודורשת אישור — תחובר בשלב 4.</p>
      </Panel>

      {/* manual actions (visual) */}
      <Panel title="🔧 פעולות ידניות (בדיקה)">
        <button className="rounded-lg border border-border bg-surface2 px-4 py-2 text-sm text-text2">▶️ פתח עסקאות לפקיעות השבוע</button>
        <p className="mt-2 text-xs text-text3">פעולה ידנית לבדיקה — פותחת עסקאות בכל התיקים. תחובר בשלב 4.</p>
      </Panel>

      <p className="pt-1 text-xs text-text3">⚠️ כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה היסטורית.</p>
    </div>
  );
}
