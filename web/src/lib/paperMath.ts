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

// יתרה נגזרת: initial − (עלות+עמלה של פתוחות) + Σ pnl של סגורות.
export function computeBalance(
  initial: number,
  trades: Pick<TradeLite, "status" | "entry_cost" | "entry_commission" | "pnl">[],
): number {
  let balance = initial;
  for (const t of trades) {
    if (t.status === "open") {
      balance -= Number(t.entry_cost ?? 0) + Number(t.entry_commission ?? 0);
    } else if (t.status === "closed") {
      balance += Number(t.pnl ?? 0);
    }
  }
  return Math.round(balance * 10000) / 10000;
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
