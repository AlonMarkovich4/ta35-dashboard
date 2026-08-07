import { describe, it, expect } from "vitest";
import { computeRealized, computeOpenExposure, parseLegs, returnOnRisk } from "@/lib/paperMath";

describe("returnOnRisk", () => {
  // רגרסיה: המסך הציג ‎-7726.3% על עסקה אמיתית בתיק 8 (פקיעה 30/07/2026).
  // pnl_pct מחלק בקרדיט שהתקבל (‎19₪) במקום בהון בסיכון (‎1,481₪).
  it("does not blow up on a credit spread with a tiny premium", () => {
    expect(returnOnRisk(-1468, -1481)).toBeCloseTo(-0.9912, 4);
  });

  // no-op לאסטרטגיות דביט: אצלן |entry_cost| == |max_loss|, ולכן התוצאה
  // זהה למה ש-pnl_pct הראה קודם. תיק 7, פקיעה 16/06/2026.
  it("matches the old number for a debit strategy", () => {
    expect(returnOnRisk(1777, -237)).toBeCloseTo(7.4979, 4);
  });

  it("uses the magnitude of max_loss regardless of its sign", () => {
    expect(returnOnRisk(500, -1000)).toBe(returnOnRisk(500, 1000));
  });

  it("returns null when there is no pnl (open trade)", () => {
    expect(returnOnRisk(null, -1000)).toBeNull();
    expect(returnOnRisk(undefined, -1000)).toBeNull();
  });

  // הגנה על החלוקה: max_loss חסר או אפס ⇒ אין תשואה להציג, לא Infinity.
  it("returns null instead of dividing by zero", () => {
    expect(returnOnRisk(500, 0)).toBeNull();
    expect(returnOnRisk(500, null)).toBeNull();
    expect(returnOnRisk(500, undefined)).toBeNull();
  });

  it("returns null on non-finite input", () => {
    expect(returnOnRisk(Number.NaN, -1000)).toBeNull();
    expect(returnOnRisk(500, Number.NaN)).toBeNull();
  });
});

describe("computeRealized", () => {
  it("adds pnl for closed trades (ignores their entry cost)", () => {
    expect(
      computeRealized(100000, [{ status: "closed", entry_cost: 999, entry_commission: 999, pnl: 500 }]),
    ).toBe(100500);
  });

  it("open trades contribute nothing — a paid debit is not a loss yet", () => {
    expect(
      computeRealized(100000, [{ status: "open", entry_cost: 2000, entry_commission: 10, pnl: null }]),
    ).toBe(100000);
  });

  // רגרסיה: תיק ההמלצות (id=8) הציג +1,824₪ תשואה כשרק +40₪ מומשו — הפרמיה
  // של 4 קונדורים פתוחים (entry_cost שלילי = זיכוי) נספרה כרווח לפני הסגירה.
  it("does NOT book the premium of an open credit condor as profit", () => {
    const recoPortfolio = [
      { status: "closed", entry_cost: -60, entry_commission: 10, pnl: 40 },
      { status: "open", entry_cost: -277, entry_commission: 10, pnl: null },
      { status: "open", entry_cost: -387, entry_commission: 10, pnl: null },
      { status: "open", entry_cost: -497, entry_commission: 10, pnl: null },
      { status: "open", entry_cost: -663, entry_commission: 10, pnl: null },
    ];
    expect(computeRealized(100000, recoPortfolio)).toBe(100040); // ולא 101824
  });

  it("mixes open and closed trades", () => {
    expect(
      computeRealized(100000, [
        { status: "open", entry_cost: 1000, entry_commission: 5, pnl: null },
        { status: "closed", entry_cost: 0, entry_commission: 0, pnl: 300 },
      ]),
    ).toBe(100300);
  });

  it("ignores unknown statuses and treats null pnl as 0", () => {
    expect(
      computeRealized(100000, [
        { status: "skipped", entry_cost: 5000, entry_commission: 5000, pnl: 5000 },
        { status: "closed", entry_cost: null, entry_commission: null, pnl: null },
      ]),
    ).toBe(100000);
  });

  it("rounds to 4 decimals", () => {
    expect(
      computeRealized(0, [{ status: "closed", entry_cost: null, entry_commission: null, pnl: 0.123456 }]),
    ).toBe(0.1235);
  });
});

describe("computeOpenExposure", () => {
  it("reports a credit condor's collected premium as positive cash flow, net of commission", () => {
    const e = computeOpenExposure([
      { status: "open", entry_cost: -277, entry_commission: 10, pnl: null, max_loss: 1500 },
      { status: "open", entry_cost: -387, entry_commission: 10, pnl: null, max_loss: 2000 },
    ]);
    expect(e).toEqual({ count: 2, cashFlow: 644, atRisk: 3500 }); // 277+387 − 20
  });

  it("reports a paid debit as negative cash flow", () => {
    const e = computeOpenExposure([
      { status: "open", entry_cost: 580, entry_commission: 10, pnl: null, max_loss: null },
    ]);
    expect(e).toEqual({ count: 1, cashFlow: -590, atRisk: 0 });
  });

  it("excludes closed trades entirely", () => {
    const e = computeOpenExposure([
      { status: "closed", entry_cost: -60, entry_commission: 10, pnl: 40, max_loss: 900 },
    ]);
    expect(e).toEqual({ count: 0, cashFlow: 0, atRisk: 0 });
  });
});

describe("parseLegs", () => {
  it("maps the real legs_json shape (price_nis, not price_ils)", () => {
    const raw = [{ qty: 1, type: "Call", action: "קנה", strike: 4420, price_nis: 570, price_pts: 11.4 }];
    expect(parseLegs(raw)).toEqual([
      { action: "קנה", type: "Call", strike: 4420, qty: 1, pts: 11.4, nis: 570 },
    ]);
  });

  it("parses a JSON string", () => {
    const s = JSON.stringify([
      { action: "מכור", type: "Put", strike: 4000, qty: 2, price_pts: 9, price_nis: 450 },
    ]);
    expect(parseLegs(s)[0]).toMatchObject({ action: "מכור", strike: 4000, qty: 2, pts: 9, nis: 450 });
  });

  it("uses fallback keys (side / option_type / quantity / price / nis)", () => {
    const raw = [{ side: "buy", option_type: "Put", quantity: 3, price: 5, nis: 250 }];
    expect(parseLegs(raw)[0]).toEqual({ action: "buy", type: "Put", strike: 0, qty: 3, pts: 5, nis: 250 });
  });

  it("defaults qty to 1 when missing", () => {
    expect(parseLegs([{ strike: 4100 }])[0].qty).toBe(1);
  });

  // מחיר לא ידוע: 4 העסקאות הראשונות בתיק ההמלצות (30–34) נכתבו עם price_pts=0
  // כי המחירים לא נשמרו. 0 אינו מחיר — הוא "לא ידוע", והתצוגה חייבת להראות "—".
  it("maps a zero price to null (unknown), not 0", () => {
    const raw = [{ action: "מכור", type: "Put", strike: 3980, qty: 1, price_pts: 0, price_nis: 0 }];
    const leg = parseLegs(raw)[0];
    expect(leg.pts).toBeNull();
    expect(leg.nis).toBeNull();
    expect(leg.strike).toBe(3980); // ה-strike עדיין נשמר
  });

  it("maps a missing price to null", () => {
    const leg = parseLegs([{ action: "קנה", type: "Call", strike: 4150, qty: 1 }])[0];
    expect(leg.pts).toBeNull();
    expect(leg.nis).toBeNull();
  });

  it("keeps real prices as numbers", () => {
    const raw = [{ action: "מכור", type: "Put", strike: 3980, qty: 1, price_pts: 6.5, price_nis: 325 }];
    const leg = parseLegs(raw)[0];
    expect(leg.pts).toBe(6.5);
    expect(leg.nis).toBe(325);
  });

  it("returns [] for non-array input", () => {
    expect(parseLegs({ not: "array" })).toEqual([]);
    expect(parseLegs(null)).toEqual([]);
  });

  it("returns [] for an invalid JSON string", () => {
    expect(parseLegs("{not json")).toEqual([]);
  });
});
