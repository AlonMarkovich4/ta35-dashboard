import { describe, it, expect } from "vitest";
import { computeBalance, parseLegs } from "@/lib/paperMath";

describe("computeBalance", () => {
  it("subtracts entry cost + commission for open trades", () => {
    expect(
      computeBalance(100000, [{ status: "open", entry_cost: 2000, entry_commission: 10, pnl: null }]),
    ).toBe(97990);
  });

  it("adds pnl for closed trades (ignores their entry cost)", () => {
    expect(
      computeBalance(100000, [{ status: "closed", entry_cost: 999, entry_commission: 999, pnl: 500 }]),
    ).toBe(100500);
  });

  it("mixes open and closed trades", () => {
    expect(
      computeBalance(100000, [
        { status: "open", entry_cost: 1000, entry_commission: 5, pnl: null },
        { status: "closed", entry_cost: 0, entry_commission: 0, pnl: 300 },
      ]),
    ).toBe(99295);
  });

  it("ignores unknown statuses and treats null numbers as 0", () => {
    expect(
      computeBalance(100000, [
        { status: "skipped", entry_cost: 5000, entry_commission: 5000, pnl: 5000 },
        { status: "open", entry_cost: null, entry_commission: null, pnl: null },
      ]),
    ).toBe(100000);
  });

  it("rounds to 4 decimals", () => {
    expect(
      computeBalance(0, [{ status: "closed", entry_cost: null, entry_commission: null, pnl: 0.123456 }]),
    ).toBe(0.1235);
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

  it("returns [] for non-array input", () => {
    expect(parseLegs({ not: "array" })).toEqual([]);
    expect(parseLegs(null)).toEqual([]);
  });

  it("returns [] for an invalid JSON string", () => {
    expect(parseLegs("{not json")).toEqual([]);
  });
});
