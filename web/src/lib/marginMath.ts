// תורגם 1:1 מ-src/margin_validator.py — אין לשנות נוסחאות.
//
// שכבת הולידציה של מנגנון המרווח ("המנוע מול המציאות"): מחברת המלצות מרווח
// (margin_recommendations) למציאות (settlement ב-condor_settled_detail + move_pct
// ב-expiry_history). לוגיקה טהורה בלבד — אין DB, אין server-only. השאילתות חיות
// ב-data.ts (getMarginData); כאן רק בחירת ההמלצה האחרונה, ה-held/optimal_hindsight/פער,
// והסיכום. Unit-tested מול tests/test_margin_validator.py (אותם מקרים, אותן תוצאות).
//
// היקף מכוון: est_pnl (margin_pnl → payoff_iron_condor) אינו מפורט כאן. התצוגה מציגה
// עקביות (החזיק/אופטימום/פער), ושחזור ה-P&L נשאר צד-שרת/Python (indicative בלבד, והיה
// דורש port של כל מנוע ה-payoff). מקור התנועה: expiry_history הקנוני, settlement כגיבוי.

import { asDateKey } from "@/lib/validationMath"; // === _as_date (משותף, כבר 1:1 מהמקור)

export { asDateKey };

// ─── טיפוסי קלט (אחרי SELECT + חילוץ recommendation_json ב-data.ts) ───────

export type MarginRecommendation = {
  expiryDate: unknown; // DATE — Date | string מהדרייבר
  recommendedAt: unknown; // timestamp — לבחירת האחרונה
  marginPct: number | null; // המרווח שהומלץ
  baseIndex: number | null; // recommendation_json.base_index (לגיבוי חישוב התנועה)
  gridMargins: number[]; // recommendation_json.grid[].margin_pct (לאופטימום בדיעבד)
};

// ─── טיפוסי פלט ──────────────────────────────────────────────────────────

export type MarginValidationRow = {
  expiryKey: string; // YYYY-MM-DD מנורמל
  recommendedMargin: number; // המרווח שהומלץ
  actualMovePct: number; // התנועה בפועל (חתומה)
  actualAbsMovePct: number; // |move|
  moveSource: "expiry_history" | "settlement";
  held: boolean; // |move| ≤ margin
  marginOptimalHindsight: number | null; // הצר ביותר שהיה מחזיק; null אם חרגה מהגריד
  marginGap: number | null; // recommended − optimal (חתום); null אם optimal=null
};

export type MarginValidationSummary = {
  nValidated: number;
  holdRate: number; // [0,1] — העקביות בפועל
  nHeld: number;
  avgMarginGap: number; // פער ממוצע מהאופטימום
};

// ─── helpers ─────────────────────────────────────────────────────────────

const round4 = (x: number): number => Math.round(x * 1e4) / 1e4;
const round2 = (x: number): number => Math.round(x * 100) / 100;

// חותמת-זמן להשוואה (Date/מחרוזת-ISO) — לבחירת ההמלצה האחרונה. לא-פריק → 0.
function timeOf(v: unknown): number {
  if (v instanceof Date) return v.getTime();
  const t = new Date(String(v)).getTime();
  return Number.isNaN(t) ? 0 : t;
}

// גריד ברירת המחדל: 1.0%–3.0% בקפיצות 0.25% — מקביל ל-_default_margins של המקור.
export function defaultMargins(): number[] {
  return Array.from({ length: 9 }, (_, i) => round2(1.0 + 0.25 * i));
}

// ─── בחירת ההמלצה האחרונה לכל פקיעה (=== DISTINCT ON expiry_date, MAX recommended_at) ─

// מקביל ל-_fetch_latest_recommendations של המקור (שם הבחירה נעשית ב-SQL). כאן טהור
// וגנרי: לכל פקיעה (asDateKey) נבחרת הרשומה עם recommended_at המקסימלי. סדר-קלט לא משנה.
export function pickLatestRecommendations<
  T extends { expiryDate: unknown; recommendedAt: unknown },
>(recs: T[]): T[] {
  const latest = new Map<string, T>();
  for (const r of recs) {
    const key = asDateKey(r.expiryDate);
    if (key == null) continue;
    const cur = latest.get(key);
    if (!cur || timeOf(r.recommendedAt) >= timeOf(cur.recommendedAt)) latest.set(key, r);
  }
  return [...latest.values()];
}

// ─── האופטימום בדיעבד ────────────────────────────────────────────────────

// המרווח הצר ביותר בגריד שהיה מחזיק את התנועה (m ≥ |move|); null אם חרגה מכל הגריד.
// משתמש בגריד של ההמלצה עצמה; נופל לגריד הנומינלי. מקביל 1:1 ל-_optimal_hindsight.
export function optimalHindsight(absMove: number, gridMargins: number[]): number | null {
  const margins = gridMargins.length
    ? [...new Set(gridMargins.map(round4))].sort((a, b) => a - b)
    : defaultMargins();
  const holders = margins.filter((m) => m >= absMove);
  return holders.length ? Math.min(...holders) : null;
}

// ─── public API ──────────────────────────────────────────────────────────

// מחבר המלצות מרווח (האחרונה לכל פקיעה) למציאות — שורה לכל פקיעה "ולידבילית" (יש לה גם
// המלצה וגם settlement). מקביל 1:1 ל-build_margin_validation_rows, למעט שהקריאות ל-DB
// נעשות ב-data.ts. מקור התנועה: expiry_history קודם (הקנוני, אותה הגדרת held כמו הבקטסט),
// settlement כגיבוי ((close − base_index)/base_index). ללא settlement → לא ולידבילית.
export function buildMarginValidationRows(
  latestRecs: MarginRecommendation[],
  settlements: Map<string, number>, // expiryKey → actual_index_close
  historyMoves: Map<string, number>, // expiryKey → move_pct
): MarginValidationRow[] {
  const rows: MarginValidationRow[] = [];
  for (const rec of latestRecs) {
    const exp = asDateKey(rec.expiryDate);
    if (exp == null) continue;
    const close = settlements.get(exp);
    if (close == null) continue; // לא נסגרה (אין settlement) — לא ולידבילית

    // מקור התנועה: מעדיפים expiry_history הקנוני, נופלים ל-settlement.
    let move: number;
    let source: "expiry_history" | "settlement";
    const hm = historyMoves.get(exp);
    if (hm != null) {
      move = hm;
      source = "expiry_history";
    } else if (rec.baseIndex != null && rec.baseIndex !== 0) {
      move = ((close - rec.baseIndex) / rec.baseIndex) * 100;
      source = "settlement";
    } else {
      continue; // אין מקור בר-חישוב
    }

    const rmargin = rec.marginPct;
    if (rmargin == null) continue;
    const absMove = Math.abs(move);
    const held = absMove <= rmargin;
    const optimal = optimalHindsight(absMove, rec.gridMargins);
    const gap = optimal == null ? null : round4(rmargin - optimal);

    rows.push({
      expiryKey: exp,
      recommendedMargin: round4(rmargin),
      actualMovePct: round4(move),
      actualAbsMovePct: round4(absMove),
      moveSource: source,
      held,
      marginOptimalHindsight: optimal,
      marginGap: gap,
    });
  }

  // מיון לפי expiry יורד (האחרונה ראשונה). YYYY-MM-DD ⇒ מיון לקסיקלי = כרונולוגי.
  rows.sort((a, b) => (a.expiryKey < b.expiryKey ? 1 : a.expiryKey > b.expiryKey ? -1 : 0));
  return rows;
}

// שדות המינימום לסיכום — מאפשר לבדיקות להזין שורות חלקיות (כמו במקור).
type SummarizableMarginRow = Pick<MarginValidationRow, "held" | "marginGap">;

// מסכם שורות ולידציה. מקביל 1:1 ל-summarize_margin_validation: n, hold_rate בפועל,
// n_held, פער ממוצע מהאופטימום (None-ים מדולגים). רשימה ריקה → כל האפסים.
export function summarizeMarginValidation(rows: SummarizableMarginRow[]): MarginValidationSummary {
  const n = rows.length;
  if (n === 0) return { nValidated: 0, holdRate: 0, nHeld: 0, avgMarginGap: 0 };
  const nHeld = rows.filter((r) => r.held).length;
  const gaps = rows.map((r) => r.marginGap).filter((g): g is number => g != null);
  return {
    nValidated: n,
    holdRate: round4(nHeld / n),
    nHeld,
    avgMarginGap: gaps.length ? round4(gaps.reduce((s, g) => s + g, 0) / gaps.length) : 0,
  };
}

// ─── רגלי ההגנה (long) — לתצוגת 4 הרגליים המלאות (שלב 6ג) ─────────────────

export type WingLegs = {
  longPutStrike: number | null;
  longCallStrike: number | null;
  maxLoss: number | null;
  wingPct: number | null; // הכנף שהונחה; null = לא ידוע (המלצה ישנה מלפני שלב 6)
  legsSource: "recorded" | "computed" | "none";
};

// חישוב long strikes מ-short ± מרחק-הכנף — fallback כשה-long strikes לא נשמרו ב-json.
// מקביל לרעיון condor_legs_from_chain: ה-long במרחק wing% (מהמדד) *מעבר ל-short*, מעוגל
// ל-10 הקרוב. קירוב (ה-strike האמיתי מהשרשרת עדיף) — לכן legsSource="computed" מסומן ב-UI.
export function computeLongStrikes(
  shortPut: number | null,
  shortCall: number | null,
  baseIndex: number | null,
  wingPct: number | null,
): { longPut: number; longCall: number } | null {
  if (shortPut == null || shortCall == null || baseIndex == null || wingPct == null) return null;
  const wingPts = baseIndex * (wingPct / 100);
  const round10 = (x: number) => Math.round(x / 10) * 10;
  return { longPut: round10(shortPut - wingPts), longCall: round10(shortCall + wingPts) };
}

// פותר את רגלי ההגנה לתצוגה: מעדיף long strikes שנרשמו ב-json (legsSource="recorded");
// נופל לחישוב מ-short±wing ("computed"); אם אין wing כלל (המלצה ישנה) ולא נרשמו longs →
// "none" (ה-UI יציג "—"). ה-wingPct נפתר במעלה הזרם (top-level ?? selected_curve_row).
export function resolveWingLegs(input: {
  shortPutStrike: number | null;
  shortCallStrike: number | null;
  baseIndex: number | null;
  recordedLongPut: number | null;
  recordedLongCall: number | null;
  maxLoss: number | null;
  wingPct: number | null;
}): WingLegs {
  const { shortPutStrike, shortCallStrike, baseIndex, recordedLongPut, recordedLongCall, maxLoss, wingPct } = input;
  if (recordedLongPut != null && recordedLongCall != null) {
    return { longPutStrike: recordedLongPut, longCallStrike: recordedLongCall, maxLoss, wingPct, legsSource: "recorded" };
  }
  const computed = computeLongStrikes(shortPutStrike, shortCallStrike, baseIndex, wingPct);
  if (computed) {
    return { longPutStrike: computed.longPut, longCallStrike: computed.longCall, maxLoss, wingPct, legsSource: "computed" };
  }
  return { longPutStrike: null, longCallStrike: null, maxLoss, wingPct, legsSource: "none" };
}
