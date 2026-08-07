// Pure paper-trading math — no DB, no server-only. Unit-tested.

export type TradeLite = {
  portfolio_id: number;
  strategy_name: string | null;
  expiry_date: string | null;
  status: string | null;
  entry_cost: number | null;
  entry_commission: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  closed_at: string | null;
};

const r4 = (v: number) => Math.round(v * 10000) / 10000;

type PnlTrade = Pick<TradeLite, "status" | "entry_cost" | "entry_commission" | "pnl">;

// P&L ממומש: Σ pnl של עסקאות סגורות בלבד.
//
// פוזיציה פתוחה לא תורמת כלום. במיוחד: הפרמיה שנגבתה על Short Iron Condor
// (entry_cost שלילי = זיכוי) אינה רווח — היא התחייבות פתוחה שעוד יכולה
// להימחק, ואף להפוך להפסד עד max_loss. לספור אותה כרווח לפני שהעסקה נסגרה
// מנפח את התשואה. ראה computeOpenExposure להצגת הפוזיציות הפתוחות בנפרד.
export function computeRealized(initial: number, trades: PnlTrade[]): number {
  let equity = initial;
  for (const t of trades) {
    if (t.status === "closed") equity += Number(t.pnl ?? 0);
  }
  return r4(equity);
}

// תשואה על ההון בסיכון: pnl / |max_loss|.
//
// **למה לא pnl_pct שב-DB.** העמודה הזו מחושבת כ-`pnl / |entry_cost|`, ובאסטרטגיות
// **דביט** (סטרדל, סטרנגל, פרפרים, bull call) זה נכון — `entry_cost` הוא מה ששולם,
// שהוא גם ההון בסיכון. אבל ב-**קרדיט** (Short Iron Condor, תיקים 3 ו-8) `entry_cost`
// הוא הפרמיה שהתקבלה, בעוד שההון בסיכון הוא `max_loss` — גדול ממנו בסדרי גודל.
// התוצאה במסך הייתה ‎-7726.3% על עסקה עם קרדיט ‎19₪ ו-max_loss של ‎1,481₪
// (אותה עסקה היא ‎-99.1% מההון). אומת 06/08/2026 על 193 עסקאות סגורות.
//
// המעבר הוא no-op לאסטרטגיות הדביט: אצלן |entry_cost| == |max_loss| (אומת 30/30
// בתיקים 2, 4, 5, 7; בתיק 6 ההפרש 25₪ מתוך 3,738 — עמלת הכניסה).
//
// `pnl_pct` נשאר ב-DB כרשומה היסטורית; התצוגה נגזרת, לא מאוחסנת.
export function returnOnRisk(
  pnl: number | null | undefined,
  maxLoss: number | null | undefined,
): number | null {
  if (pnl === null || pnl === undefined) return null;
  const risk = Math.abs(Number(maxLoss ?? 0));
  if (!Number.isFinite(risk) || risk === 0) return null;
  const p = Number(pnl);
  if (!Number.isFinite(p)) return null;
  return r4(p / risk);
}

export type OpenExposure = {
  count: number;    // כמה פוזיציות פתוחות
  cashFlow: number; // תזרים בפועל על הפתוחות: חיובי = פרמיה שנגבתה, שלילי = עלות ששולמה
  atRisk: number;   // סכום max_loss של הפתוחות (0 אם לא ידוע) — ההפסד התיאורטי המרבי
};

// חשיפה פתוחה — מוצגת בנפרד מה-P&L, אף פעם לא מתווספת לתשואה.
// cashFlow = −Σ(entry_cost + עמלה) על הפתוחות: זהו התזרים שכבר עבר בחשבון,
// אבל התוצאה של העסקאות האלה עדיין לא ידועה.
export function computeOpenExposure(
  trades: (PnlTrade & { max_loss?: number | null })[],
): OpenExposure {
  let count = 0, cashFlow = 0, atRisk = 0;
  for (const t of trades) {
    if (t.status !== "open") continue;
    count += 1;
    cashFlow -= Number(t.entry_cost ?? 0) + Number(t.entry_commission ?? 0);
    atRisk += Math.abs(Number(t.max_loss ?? 0));
  }
  return { count, cashFlow: r4(cashFlow), atRisk: r4(atRisk) };
}

// pts/nis הם null כשמחיר הרגל לא ידוע — עסקאות שנפתחו לפני שמחירי הרגליים נשמרו
// (ה-chain ההיסטורי נדרס, אי-אפשר לשחזר). התצוגה מציגה "—", לא ₪0.
export type LegData = {
  action: string; type: string; strike: number; qty: number;
  pts: number | null; nis: number | null;
};

// מחיר רגל: null כשחסר/לא ידוע. 0 מטופל גם הוא כלא-ידוע — אופציה סחירה לעולם לא
// שווה 0 (margin_calculator פוסל רגל עם price<=0), ולכן 0 ב-DB הוא הערך שנכתב
// כשהמחיר לא נשמר — לא מחיר אמיתי.
function legPrice(...cands: unknown[]): number | null {
  for (const c of cands) {
    if (c === null || c === undefined || c === "") continue;
    const n = Number(c);
    if (Number.isFinite(n) && n > 0) return n;
  }
  return null;
}

// מיפוי גמיש מ-legs_json (מאומת מול הדאטה: price_nis, price_pts, action, type, strike, qty).
export function parseLegs(raw: unknown): LegData[] {
  try {
    const arr = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (!Array.isArray(arr)) return [];
    return arr.map((l: Record<string, unknown>) => ({
      action: String(l.action ?? l.side ?? ""),
      type: String(l.type ?? l.option_type ?? ""),
      strike: Number(l.strike ?? 0),
      qty: Number(l.qty ?? l.quantity ?? l.contracts ?? 1),
      pts: legPrice(l.price_pts, l.pts, l.price),
      nis: legPrice(l.price_nis, l.price_ils, l.nis),
    }));
  } catch {
    return [];
  }
}
