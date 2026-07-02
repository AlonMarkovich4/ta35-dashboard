// Pure option-chain math — no DB, no server-only. Unit-tested.

const MULTIPLIER = 50; // ₪ לנקודה

export type AtmInput = { strike: number; callNis: number; putNis: number; callDelta: number };

// find_atm (1:1 מ-options_parser.py): put-call parity → fallback delta≈0.5 →
// fallback ממוצע סטרייקים. אין שימוש ב-underlingasset.
export function findAtm(rows: AtmInput[]): { atmStrike: number | null; indexEstimate: number | null } {
  let atmStrike: number | null = null;
  let indexEstimate: number | null = null;

  const parity = rows.filter((r) => r.callNis > 0 && r.putNis > 0);
  if (parity.length) {
    const a = parity.reduce((x, y) =>
      Math.abs(y.callNis - y.putNis) < Math.abs(x.callNis - x.putNis) ? y : x,
    );
    atmStrike = a.strike;
    indexEstimate = a.strike + (a.callNis - a.putNis) / MULTIPLIER;
  } else if (rows.length) {
    const a = rows.reduce((x, y) =>
      Math.abs(y.callDelta - 0.5) < Math.abs(x.callDelta - 0.5) ? y : x,
    );
    // אם קיים דלתא שימושי — ATM לפי delta≈0.5; אחרת ממוצע סטרייקים (atmStrike=null)
    if (rows.some((r) => r.callDelta > 0)) {
      atmStrike = a.strike;
      indexEstimate = a.strike;
    } else {
      indexEstimate = rows.reduce((s, r) => s + r.strike, 0) / rows.length;
    }
  }

  return { atmStrike, indexEstimate };
}
