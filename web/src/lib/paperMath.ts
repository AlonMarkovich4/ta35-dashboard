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

export type LegData = { action: string; type: string; strike: number; qty: number; pts: number; nis: number };

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
      pts: Number(l.price_pts ?? l.pts ?? l.price ?? 0),
      nis: Number(l.price_nis ?? l.price_ils ?? l.nis ?? 0),
    }));
  } catch {
    return [];
  }
}
