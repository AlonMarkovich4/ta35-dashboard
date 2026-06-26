const isNum = (v: unknown): v is number =>
  typeof v === "number" && !Number.isNaN(v);

// מספר שלם עם מפרידי אלפים (ספרות מערביות); "—" כשאין ערך
export const en = (v: number | null | undefined): string =>
  isNum(v) ? Math.round(v).toLocaleString("en-US") : "—";

// מספר מלא (שומר עשרוניים)
export const num = (v: number | null | undefined): string =>
  isNum(v) ? v.toLocaleString("en-US") : "—";

// כסף ללא סימן: "₪110,521"
export const ils = (v: number | null | undefined): string =>
  isNum(v) ? `₪${en(v)}` : "—";

// כסף עם סימן: "+₪10,521" / "-₪1,200"
export const money = (v: number | null | undefined): string =>
  isNum(v)
    ? `${v > 0 ? "+" : v < 0 ? "-" : ""}₪${Math.abs(Math.round(v)).toLocaleString("en-US")}`
    : "—";

// אחוז ממספר-אחוז (58.3 → "58.3%")
export const pct = (v: number | null | undefined, digits = 1): string =>
  isNum(v) ? `${v.toFixed(digits)}%` : "—";

// אחוז משבר (fraction) (0.068 → "6.8%")
export const pctFrac = (v: number | null | undefined, digits = 1): string =>
  isNum(v) ? `${(v * 100).toFixed(digits)}%` : "—";

// אחוז משבר עם סימן (0.068 → "+6.8%")
export const signedPctFrac = (v: number | null | undefined, digits = 1): string =>
  isNum(v) ? `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%` : "—";

// class צבע לערכי P&L
export const pnlTone = (v: number | null | undefined): string =>
  isNum(v) ? (v > 0 ? "text-pos" : v < 0 ? "text-neg" : "text-text2") : "text-text3";
