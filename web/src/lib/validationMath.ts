// תורגם 1:1 מ-src/decision_validator.py — אין לשנות נוסחאות.
//
// שכבת "המנוע מול המציאות": מחברת תחזיות המנוע (decision_log) לרווח האמיתי
// (paper_trades). לוגיקה טהורה בלבד — אין DB, אין server-only. שתי שאילתות ה-SELECT
// חיות ב-data.ts (getValidation); כאן רק החיבור, בחירת ה-best/hit/regret, והסיכום.
// Unit-tested מול tests/test_decision_validator.py (אותם מקרים, אותן תוצאות).

import { STRATEGIES } from "@/lib/strategies";

// מיפוי {strategy_id → שם} מה-registry, ל-fallback כשאין שם שנשמר בעסקה.
const STRAT_BY_ID = new Map<number, string>(STRATEGIES.map((s) => [s.id, s.name]));

// ─── טיפוסי קלט (צורת השורות שהדרייבר מחזיר משתי השאילתות) ────────────────

export type LatestDecision = {
  expiry_date: unknown; // DATE — Date | string מהדרייבר
  engine_version: string | null;
  decided_at: unknown; // timestamp
  top_strategy_id: number | null;
  regime: string | null;
  n_decisions: number;
};

export type ClosedPnl = {
  expiry_date: unknown;
  strategy_id: number | null;
  strategy_name: string | null;
  pnl: number | null;
  n_trades: number;
};

// ─── טיפוסי פלט ──────────────────────────────────────────────────────────

export type ValidationRow = {
  expiryKey: string; // YYYY-MM-DD מנורמל (מפתח החיבור + מקור לתצוגה)
  decidedAt: unknown;
  topStrategyId: number | null;
  topStrategyName: string;
  recommendedPnl: number | null; // null אם המומלצת לא נסגרה
  bestStrategyId: number | null;
  bestStrategyName: string;
  bestPnl: number;
  worstPnl: number;
  avgPnl: number;
  hit: boolean;
  regret: number | null; // best - recommended; 0 אם פגע; null אם אין P&L להמלצה
  regime: string | null;
  nDecisions: number;
};

export type ValidationSummary = {
  nValidated: number;
  hitRate: number; // [0,1]
  recommendedPnl: number;
  bestPnl: number;
  avgPnl: number;
  totalRegret: number;
};

// ─── helpers ─────────────────────────────────────────────────────────────

// מנרמל ערך expiry_date (Date/מחרוזת-ISO) למפתח YYYY-MM-DD אחיד — מקביל ל-_as_date
// של המקור. שקול ל-CAST ::date, אך בצד JS. None/לא-פריק → null. שני צדי החיבור
// עוברים דרך אותה פונקציה, כך שהמפתחות עקביים ללא תלות בטיפוס שהדרייבר מחזיר.
export function asDateKey(v: unknown): string | null {
  if (v == null) return null;
  if (v instanceof Date) {
    return Number.isNaN(v.getTime()) ? null : v.toISOString().slice(0, 10);
  }
  const s = String(v);
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(s); // מחרוזת ISO (date או datetime) → חלק התאריך
  if (m) return m[1];
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
}

// שם אסטרטגיה לתצוגה: קודם השם שנשמר בעסקה (authoritative), אחרת ה-registry, אחרת ה-id.
// מקביל ל-_strategy_name של המקור.
function strategyName(sid: number | null, tradeNames: Map<number, string | null>): string {
  if (sid == null) return "—";
  const nm = tradeNames.get(sid);
  if (nm) return nm;
  const reg = STRAT_BY_ID.get(sid);
  if (reg) return reg;
  return String(sid);
}

// ─── public API ──────────────────────────────────────────────────────────

// מחבר תחזיות המנוע לרווח האמיתי — שורה אחת לכל פקיעה "ולידבילית" (יש לה גם
// החלטה מתועדת וגם עסקאות שנסגרו). מקביל 1:1 ל-build_validation_rows של המקור,
// למעט ששתי הקריאות ל-DB נעשות ב-data.ts ומוזרקות כאן כמערכים.
export function buildValidationRows(
  decisions: LatestDecision[],
  trades: ClosedPnl[],
): ValidationRow[] {
  // אינדוקס עסקאות סגורות לפי פקיעה → Map<strategy_id, {pnl, name}>
  const byExpiry = new Map<string, Map<number, { pnl: number; name: string | null }>>();
  for (const t of trades) {
    const exp = asDateKey(t.expiry_date);
    const sid = t.strategy_id;
    if (exp == null || sid == null || t.pnl == null) continue;
    if (!byExpiry.has(exp)) byExpiry.set(exp, new Map());
    byExpiry.get(exp)!.set(sid, { pnl: t.pnl, name: t.strategy_name });
  }

  const rows: ValidationRow[] = [];
  for (const dec of decisions) {
    const exp = asDateKey(dec.expiry_date);
    if (exp == null) continue;
    const stratMap = byExpiry.get(exp);
    if (!stratMap || stratMap.size === 0) continue; // החלטה בלי עסקאות סגורות — לא ולידבילית

    const pnls = new Map<number, number>();
    const tradeNames = new Map<number, string | null>();
    for (const [sid, v] of stratMap) {
      pnls.set(sid, v.pnl);
      tradeNames.set(sid, v.name);
    }

    const pnlVals = [...pnls.values()];
    const bestPnl = Math.max(...pnlVals);
    const worstPnl = Math.min(...pnlVals);
    const avgPnl = pnlVals.reduce((s, p) => s + p, 0) / pnlVals.length;

    const topId = dec.top_strategy_id;
    const recPnl = topId != null && pnls.has(topId) ? pnls.get(topId)! : null;

    let hit: boolean;
    let bestId: number | null;
    let bestVal: number;
    let regret: number | null;
    if (recPnl != null && recPnl === bestPnl) {
      // פגיעה (כולל תיקו על המקסימום): מציגים את המומלצת כטובה ביותר, regret=0
      hit = true;
      bestId = topId;
      bestVal = recPnl;
      regret = 0;
    } else {
      hit = false;
      // שובר-תיקו דטרמיניסטי: מבין בעלי ה-P&L המקסימלי, ה-strategy_id הנמוך
      bestId = Math.min(
        ...[...pnls.entries()].filter(([, p]) => p === bestPnl).map(([sid]) => sid),
      );
      bestVal = bestPnl;
      regret = recPnl != null ? bestPnl - recPnl : null;
    }

    rows.push({
      expiryKey: exp,
      decidedAt: dec.decided_at,
      topStrategyId: topId,
      topStrategyName: strategyName(topId, tradeNames),
      recommendedPnl: recPnl,
      bestStrategyId: bestId,
      bestStrategyName: strategyName(bestId, tradeNames),
      bestPnl: bestVal,
      worstPnl,
      avgPnl,
      hit,
      regret,
      regime: dec.regime,
      nDecisions: dec.n_decisions,
    });
  }

  // מיון לפי expiry יורד (האחרונה ראשונה). המפתח YYYY-MM-DD ⇒ מיון לקסיקלי = כרונולוגי.
  rows.sort((a, b) => (a.expiryKey < b.expiryKey ? 1 : a.expiryKey > b.expiryKey ? -1 : 0));
  return rows;
}

// שדות המינימום הדרושים לסיכום — מאפשר לבדיקות להזין שורות חלקיות (כמו במקור).
type SummarizableRow = Pick<
  ValidationRow,
  "hit" | "recommendedPnl" | "bestPnl" | "avgPnl" | "regret"
>;

// מסכם שורות ולידציה למדדי-על. מקביל 1:1 ל-summarize_validation של המקור:
// None/null ב-recommended_pnl ו-regret מדולגים בסכימה. רשימה ריקה → כל האפסים.
export function summarizeValidation(rows: SummarizableRow[]): ValidationSummary {
  const n = rows.length;
  if (n === 0) {
    return { nValidated: 0, hitRate: 0, recommendedPnl: 0, bestPnl: 0, avgPnl: 0, totalRegret: 0 };
  }
  const hits = rows.filter((r) => r.hit).length;
  const sum = (f: (r: SummarizableRow) => number | null): number =>
    rows.reduce((s, r) => {
      const v = f(r);
      return v == null ? s : s + v;
    }, 0);
  return {
    nValidated: n,
    hitRate: hits / n,
    recommendedPnl: sum((r) => r.recommendedPnl),
    bestPnl: sum((r) => r.bestPnl),
    avgPnl: sum((r) => r.avgPnl),
    totalRegret: sum((r) => r.regret),
  };
}
