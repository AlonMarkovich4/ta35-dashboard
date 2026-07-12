import { describe, it, expect } from "vitest";
import {
  asDateKey,
  buildMarginValidationRows,
  optimalHindsight,
  pickLatestRecommendations,
  summarizeMarginValidation,
  type MarginRecommendation,
} from "@/lib/marginMath";

// משכפל את tests/test_margin_validator.py: אותם מקרים, אותן תוצאות.
// (בחירת ההמלצה האחרונה נעשית ב-SQL DISTINCT ON במקור; כאן היא פונקציה טהורה
//  שנבדקת ישירות, ומזינה את יתר הלוגיקה.)

const rec = (
  expiry: string,
  margin: number | null,
  extra: Partial<MarginRecommendation> = {},
): MarginRecommendation => ({
  expiryDate: expiry,
  recommendedAt: "2026-06-16T10:00:00",
  marginPct: margin,
  baseIndex: 2000,
  gridMargins: [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0],
  ...extra,
});

const settle = (pairs: [string, number][]) => new Map<string, number>(pairs);
const hist = (pairs: [string, number][]) => new Map<string, number>(pairs);

describe("buildMarginValidationRows — join + held/optimal/gap", () => {
  it("basic row: held, narrowest optimal, wasted gap, prefers history", () => {
    const exp = "2026-06-19";
    const rows = buildMarginValidationRows([rec(exp, 2.0)], settle([[exp, 2010]]), hist([[exp, 0.5]]));
    expect(rows.length).toBe(1);
    const r = rows[0];
    expect(r.recommendedMargin).toBe(2.0);
    expect(r.actualAbsMovePct).toBe(0.5);
    expect(r.held).toBe(true);
    expect(r.moveSource).toBe("expiry_history");
    expect(r.marginOptimalHindsight).toBe(1.0); // הצר ביותר ≥ 0.5
    expect(r.marginGap).toBe(1.0); // 2.0 − 1.0
  });

  it("held=false on a break; gap negative (margin insufficient)", () => {
    const exp = "2026-06-19";
    const r = buildMarginValidationRows([rec(exp, 1.5)], settle([[exp, 2000]]), hist([[exp, 2.3]]))[0];
    expect(r.held).toBe(false);
    expect(r.marginOptimalHindsight).toBe(2.5); // הצר ביותר ≥ 2.3
    expect(r.marginGap).toBe(1.5 - 2.5); // -1.0
  });

  it("optimal is null when move exceeds the whole grid (>3.0%)", () => {
    const exp = "2026-06-19";
    const r = buildMarginValidationRows([rec(exp, 2.0)], settle([[exp, 2000]]), hist([[exp, 3.5]]))[0];
    expect(r.marginOptimalHindsight).toBeNull();
    expect(r.marginGap).toBeNull();
    expect(r.held).toBe(false);
  });

  it("optimal uses the recommendation's own (reduced) grid", () => {
    const exp = "2026-06-19";
    // רק 2.0 ו-3.0 הוצעו; תנועה 1.2% → האופטימום הזמין הוא 2.0.
    const r = buildMarginValidationRows(
      [rec(exp, 3.0, { gridMargins: [2.0, 3.0] })],
      settle([[exp, 2000]]),
      hist([[exp, 1.2]]),
    )[0];
    expect(r.marginOptimalHindsight).toBe(2.0);
  });

  it("falls back to settlement-computed move when no history", () => {
    const exp = "2026-06-19";
    const r = buildMarginValidationRows([rec(exp, 2.0, { baseIndex: 2000 })], settle([[exp, 2030]]), hist([]))[0];
    expect(r.moveSource).toBe("settlement");
    expect(r.actualMovePct).toBe(1.5); // (2030-2000)/2000*100
    expect(r.held).toBe(true);
  });

  it("prefers history even when settlement disagrees", () => {
    const exp = "2026-06-19";
    const r = buildMarginValidationRows([rec(exp, 2.0)], settle([[exp, 2100]]), hist([[exp, 0.4]]))[0];
    expect(r.moveSource).toBe("expiry_history");
    expect(r.actualAbsMovePct).toBe(0.4);
    expect(r.held).toBe(true);
  });

  it("recommendation without settlement is excluded (not closed)", () => {
    const exp = "2026-06-19";
    expect(buildMarginValidationRows([rec(exp, 2.0)], settle([]), hist([[exp, 0.5]]))).toEqual([]);
  });

  it("rows sorted by expiry descending", () => {
    const e1 = "2026-04-01", e2 = "2026-06-19", e3 = "2026-05-10";
    const rows = buildMarginValidationRows(
      [rec(e1, 2.0), rec(e2, 2.0), rec(e3, 2.0)],
      settle([[e1, 2000], [e2, 2000], [e3, 2000]]),
      hist([[e1, 0.3], [e2, 0.4], [e3, 0.5]]),
    );
    expect(rows.map((r) => r.expiryKey)).toEqual([e2, e3, e1]);
  });

  it("empty inputs → no rows", () => {
    expect(buildMarginValidationRows([], settle([]), hist([]))).toEqual([]);
  });
});

describe("optimalHindsight", () => {
  it("narrowest grid margin ≥ |move|, else null", () => {
    expect(optimalHindsight(0.5, [])).toBe(1.0); // default grid
    expect(optimalHindsight(1.3, [])).toBe(1.5);
    expect(optimalHindsight(3.5, [])).toBeNull();
  });
});

describe("pickLatestRecommendations — MAX recommended_at per expiry", () => {
  it("keeps the latest recommendation for each expiry, regardless of input order", () => {
    const exp = "2026-06-19";
    const older = rec(exp, 2.0, { recommendedAt: "2026-06-15T09:00:00" });
    const newer = rec(exp, 1.75, { recommendedAt: "2026-06-17T09:00:00" });
    const picked = pickLatestRecommendations([older, newer]);
    expect(picked.length).toBe(1);
    expect(picked[0].marginPct).toBe(1.75); // newer wins
    // סדר הפוך → אותה תוצאה
    expect(pickLatestRecommendations([newer, older])[0].marginPct).toBe(1.75);
  });

  it("one row per distinct expiry", () => {
    const picked = pickLatestRecommendations([
      rec("2026-06-19", 2.0),
      rec("2026-06-26", 1.75),
    ]);
    expect(picked.map((r) => asDateKey(r.expiryDate)).sort()).toEqual(["2026-06-19", "2026-06-26"]);
  });
});

describe("summarizeMarginValidation", () => {
  it("empty → all zeros", () => {
    expect(summarizeMarginValidation([])).toEqual({
      nValidated: 0,
      holdRate: 0,
      nHeld: 0,
      avgMarginGap: 0,
    });
  });

  it("computes hold_rate, n_held and average gap", () => {
    const s = summarizeMarginValidation([
      { held: true, marginGap: 1.0 },
      { held: false, marginGap: -0.5 },
    ]);
    expect(s.nValidated).toBe(2);
    expect(s.holdRate).toBe(0.5);
    expect(s.nHeld).toBe(1);
    expect(s.avgMarginGap).toBe(0.25); // (1.0 - 0.5) / 2
  });

  it("skips null gaps in the average", () => {
    const s = summarizeMarginValidation([
      { held: true, marginGap: null },
      { held: true, marginGap: 2.0 },
    ]);
    expect(s.holdRate).toBe(1);
    expect(s.avgMarginGap).toBe(2.0); // only the non-null value
  });
});
