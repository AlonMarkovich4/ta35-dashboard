import { describe, it, expect } from "vitest";
import {
  asDateKey,
  buildValidationRows,
  summarizeValidation,
  type LatestDecision,
  type ClosedPnl,
  type ValidationRow,
} from "@/lib/validationMath";

// משכפל את tests/test_decision_validator.py: אותם מקרים, אותן תוצאות.
// (בחירת ההחלטה האחרונה נעשית ב-SQL — DISTINCT ON — ולכן כאן, כמו במקור,
//  מזינים כבר את השורה המסוננת ומוודאים שהלוגיקה משתמשת בה נכון.)

const decision = (
  expiry: string,
  topId: number | null,
  extra: Partial<LatestDecision> = {},
): LatestDecision => ({
  expiry_date: expiry,
  engine_version: "layer1-v1",
  decided_at: "2026-06-16T10:00:00",
  top_strategy_id: topId,
  regime: "calm",
  n_decisions: 1,
  ...extra,
});

const trade = (
  expiry: string,
  sid: number,
  pnl: number,
  name?: string,
): ClosedPnl => ({
  expiry_date: expiry,
  strategy_id: sid,
  strategy_name: name ?? `S${sid}`,
  pnl,
  n_trades: 1,
});

describe("buildValidationRows — join + best/hit/regret", () => {
  it("basic join: best/worst/avg/regret, miss when recommendation isn't the best", () => {
    const exp = "2026-06-17";
    const rows = buildValidationRows(
      [decision(exp, 2, { regime: "calm", n_decisions: 3 })],
      [
        trade(exp, 1, 100), trade(exp, 2, 250), trade(exp, 3, -50),
        trade(exp, 4, 0), trade(exp, 5, 400), trade(exp, 6, 200),
      ],
    );
    expect(rows.length).toBe(1);
    const r = rows[0];
    expect(r.expiryKey).toBe(exp);
    expect(r.topStrategyId).toBe(2);
    expect(r.recommendedPnl).toBe(250);
    expect(r.bestStrategyId).toBe(5);
    expect(r.bestPnl).toBe(400);
    expect(r.worstPnl).toBe(-50);
    expect(r.avgPnl).toBe((100 + 250 - 50 + 0 + 400 + 200) / 6);
    expect(r.hit).toBe(false);
    expect(r.regret).toBe(400 - 250); // 150
    expect(r.regime).toBe("calm");
    expect(r.nDecisions).toBe(3);
  });

  it("recommendation IS the best → hit=true, regret=0", () => {
    const exp = "2026-06-17";
    const r = buildValidationRows(
      [decision(exp, 5)],
      [trade(exp, 1, 100), trade(exp, 2, 250), trade(exp, 5, 400)],
    )[0];
    expect(r.hit).toBe(true);
    expect(r.bestStrategyId).toBe(5);
    expect(r.recommendedPnl).toBe(400);
    expect(r.bestPnl).toBe(400);
    expect(r.regret).toBe(0);
  });

  it("hit-on-tie: recommendation ties for max → hit=true, regret=0 (value, not id)", () => {
    const exp = "2026-06-17";
    const r = buildValidationRows(
      [decision(exp, 3)],
      [trade(exp, 3, 400), trade(exp, 5, 400), trade(exp, 1, 10)],
    )[0];
    expect(r.hit).toBe(true);
    expect(r.bestStrategyId).toBe(3); // מוצג כטובה ביותר (ההמלצה)
    expect(r.regret).toBe(0);
  });

  it("tiebreak on a MISS: lowest strategy_id among the max wins", () => {
    // ההמלצה (1) הפסידה; שתי אסטרטגיות קשורות על המקסימום (5 ו-3) — נבחר ה-id הנמוך (3).
    const exp = "2026-06-17";
    const r = buildValidationRows(
      [decision(exp, 1)],
      [trade(exp, 1, 10), trade(exp, 5, 400), trade(exp, 3, 400)],
    )[0];
    expect(r.hit).toBe(false);
    expect(r.bestStrategyId).toBe(3);
    expect(r.bestPnl).toBe(400);
    expect(r.regret).toBe(390);
  });

  it("uses the latest decision's top_strategy_id + n_decisions (DISTINCT ON upstream)", () => {
    const exp = "2026-06-17";
    const r = buildValidationRows(
      [decision(exp, 5, { decided_at: "2026-06-16T09:00:00", n_decisions: 4 })],
      [trade(exp, 5, 400), trade(exp, 2, 100)],
    )[0];
    expect(r.topStrategyId).toBe(5);
    expect(r.nDecisions).toBe(4);
    expect(r.hit).toBe(true);
  });

  it("decision without closed trades is excluded", () => {
    const expA = "2026-06-17";
    const expB = "2026-07-15";
    const rows = buildValidationRows(
      [decision(expA, 2), decision(expB, 1)],
      [trade(expA, 2, 100), trade(expA, 1, 50)],
    );
    expect(rows.map((r) => r.expiryKey)).toEqual([expA]);
  });

  it("closed trades without a decision are excluded", () => {
    const expA = "2026-06-17";
    const expB = "2026-05-20";
    const rows = buildValidationRows(
      [decision(expA, 2)],
      [trade(expA, 2, 100), trade(expA, 1, 50), trade(expB, 3, 999)],
    );
    expect(rows.map((r) => r.expiryKey)).toEqual([expA]);
  });

  it("recommended strategy missing from closed trades → recommendedPnl/regret null, hit=false", () => {
    const exp = "2026-06-17";
    const r = buildValidationRows(
      [decision(exp, 4)], // 4 לא נסגרה
      [trade(exp, 2, 100), trade(exp, 5, 300)],
    )[0];
    expect(r.recommendedPnl).toBeNull();
    expect(r.regret).toBeNull();
    expect(r.hit).toBe(false);
    expect(r.bestStrategyId).toBe(5);
  });

  it("rows sorted by expiry descending (latest first)", () => {
    const e1 = "2026-04-01", e2 = "2026-06-17", e3 = "2026-05-10";
    const rows = buildValidationRows(
      [decision(e1, 1), decision(e2, 1), decision(e3, 1)],
      [trade(e1, 1, 10), trade(e2, 1, 20), trade(e3, 1, 30)],
    );
    expect(rows.map((r) => r.expiryKey)).toEqual([e2, e3, e1]);
  });

  it("join normalizes date types: a Date on one side, ISO string on the other", () => {
    const exp = "2026-06-17";
    const r = buildValidationRows(
      [decision(new Date("2026-06-17T00:00:00Z") as unknown as string, 2)],
      [trade(exp, 2, 100), trade(exp, 5, 50)],
    )[0];
    expect(r.expiryKey).toBe(exp);
    expect(r.hit).toBe(true); // 100 > 50, ההמלצה 2 היא הטובה
  });

  it("empty inputs → no rows", () => {
    expect(buildValidationRows([], [])).toEqual([]);
  });

  // ── גארד: תיק ההמלצות (strategy_id=102) לא מזהם את ה-benchmark ──
  it("reco-portfolio trades (102) are excluded from best/hit/regret", () => {
    const exp = "2026-06-17";
    // תיק ההמלצות עשה P&L ענק — אסור שיזהם. best נשאר 5 (400), avg על 3 בלבד.
    const r = buildValidationRows(
      [decision(exp, 2)],
      [
        trade(exp, 1, 100), trade(exp, 2, 250), trade(exp, 5, 400),
        trade(exp, 102, 99999, "Short Iron Condor (המלצת מרווח)"),
      ],
    )[0];
    expect(r.bestStrategyId).toBe(5);
    expect(r.bestPnl).toBe(400);
    expect(r.recommendedPnl).toBe(250);
    expect(r.avgPnl).toBe((100 + 250 + 400) / 3); // 102 לא נכנס לממוצע
    expect(r.regret).toBe(150);
    expect(r.hit).toBe(false);
  });

  it("an expiry with ONLY reco (102) trades is not validatable", () => {
    const exp = "2026-06-17";
    const rows = buildValidationRows(
      [decision(exp, 2)],
      [trade(exp, 102, 5000, "Short Iron Condor (המלצת מרווח)")],
    );
    expect(rows).toEqual([]); // אין עסקאות benchmark סגורות → לא ולידבילית
  });
});

describe("asDateKey", () => {
  it("parses ISO date and datetime strings, Date objects, and null/invalid", () => {
    expect(asDateKey("2026-06-17")).toBe("2026-06-17");
    expect(asDateKey("2026-06-17T15:30:00")).toBe("2026-06-17");
    expect(asDateKey(new Date("2026-06-17T15:30:00Z"))).toBe("2026-06-17");
    expect(asDateKey(null)).toBeNull();
    expect(asDateKey(undefined)).toBeNull();
    expect(asDateKey("not-a-date")).toBeNull();
  });
});

describe("summarizeValidation", () => {
  it("empty → all zeros", () => {
    expect(summarizeValidation([])).toEqual({
      nValidated: 0,
      hitRate: 0,
      recommendedPnl: 0,
      bestPnl: 0,
      avgPnl: 0,
      totalRegret: 0,
    });
  });

  it("computes totals, hit_rate and total_regret across rows", () => {
    const rows = [
      { hit: true, recommendedPnl: 400, bestPnl: 400, avgPnl: 150, regret: 0 },
      { hit: false, recommendedPnl: 250, bestPnl: 400, avgPnl: 150, regret: 150 },
    ] satisfies Pick<ValidationRow, "hit" | "recommendedPnl" | "bestPnl" | "avgPnl" | "regret">[];
    const s = summarizeValidation(rows);
    expect(s.nValidated).toBe(2);
    expect(s.hitRate).toBe(0.5);
    expect(s.recommendedPnl).toBe(650);
    expect(s.bestPnl).toBe(800);
    expect(s.avgPnl).toBe(300);
    expect(s.totalRegret).toBe(150);
  });

  it("engine (recommended) beats random (avg)", () => {
    const s = summarizeValidation([
      { hit: false, recommendedPnl: 250, bestPnl: 400, avgPnl: 150, regret: 150 },
    ]);
    expect(s.recommendedPnl).toBeGreaterThan(s.avgPnl);
  });

  it("skips null recommendedPnl/regret in the sums", () => {
    const s = summarizeValidation([
      { hit: false, recommendedPnl: null, bestPnl: 300, avgPnl: 100, regret: null },
      { hit: true, recommendedPnl: 200, bestPnl: 200, avgPnl: 100, regret: 0 },
    ]);
    expect(s.nValidated).toBe(2);
    expect(s.hitRate).toBe(0.5);
    expect(s.recommendedPnl).toBe(200);
    expect(s.bestPnl).toBe(500);
    expect(s.totalRegret).toBe(0);
  });
});
