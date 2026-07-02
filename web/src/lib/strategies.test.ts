import { describe, it, expect } from "vitest";
import { runBacktest, bestPerStrategy, STRATEGIES, STRATEGY_GRID } from "@/lib/strategies";

// Synthetic moves with hand-computed win rates.
// (The real-data check — 962 moves → Iron Condor width=3 → 99.58% — is verified
//  against the DB in the dry-run; unit tests stay DB-free with known synthetic values.)
const MOVES = [0, 0.5, -0.5, 1.5, -1.5, 2.5, -2.5, 3.5, -3.5, 4.5]; // n = 10

describe("runBacktest", () => {
  const results = runBacktest(MOVES);

  it("produces one row per (strategy × variant), each over all moves", () => {
    const expected = STRATEGIES.reduce((s, st) => s + STRATEGY_GRID[st.id].length, 0);
    expect(results.length).toBe(expected);
    for (const r of results) expect(r.total).toBe(10);
  });

  it("Iron Condor width=3 wins when |move| < 3 (7 of 10)", () => {
    const ic3 = results.find((r) => r.strategyId === 2 && r.paramsRepr === "טווח=3%");
    expect(ic3?.wins).toBe(7);
    expect(ic3?.winRate).toBeCloseTo(0.7, 6);
  });

  it("Bull Call Spread wins when move > 0 (5 of 10), identical across all widths", () => {
    const bcs = results.filter((r) => r.strategyId === 1);
    expect(bcs.length).toBeGreaterThan(1);
    for (const v of bcs) expect(v.winRate).toBeCloseTo(0.5, 6);
  });

  it("empty moves → winRate 0, total 0", () => {
    for (const r of runBacktest([])) {
      expect(r.total).toBe(0);
      expect(r.winRate).toBe(0);
    }
  });
});

describe("bestPerStrategy", () => {
  const best = bestPerStrategy(runBacktest(MOVES));

  it("returns one row per strategy, sorted by winRate descending", () => {
    expect(best.length).toBe(6);
    for (let i = 1; i < best.length; i++) {
      expect(best[i - 1].winRate).toBeGreaterThanOrEqual(best[i].winRate);
    }
  });

  it("picks Iron Condor width=3 as the best condor variant (0.7)", () => {
    const ic = best.find((b) => b.strategyId === 2);
    expect(ic?.paramsRepr).toBe("טווח=3%");
    expect(ic?.winRate).toBeCloseTo(0.7, 6);
  });
});
