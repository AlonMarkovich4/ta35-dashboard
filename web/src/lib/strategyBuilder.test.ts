import { describe, it, expect } from "vitest";
import { strategyBuilder } from "@/lib/strategyBuilder";
import type { ChainRow } from "@/lib/data";

// Synthetic chain: strikes 4000..4260 step 10; call price decreasing, put increasing (₪).
const chain: ChainRow[] = [];
for (let k = 4000; k <= 4260; k += 10) {
  chain.push({
    strike: k,
    callNis: 4260 - k + 50, // > 0 for every strike
    putNis: k - 4000 + 50,
    callPts: 0,
    putPts: 0,
    callDelta: 0,
    putDelta: 0,
    callOi: 0,
    putOi: 0,
    callVol: 0,
    putVol: 0,
  });
}

describe("strategyBuilder (ATM = 4130)", () => {
  const out = strategyBuilder(4130, chain);

  it("Bull Call Spread buys ATM call, sells ATM+30", () => {
    expect(out[1].structure).toBe("Buy 4130C / Sell 4160C");
  });

  it("Iron Condor: shorts ±2%, wings ±3% (pctStrike rounds to nearest 10)", () => {
    // +2%→4210, -2%→4050, +3%→4250, -3%→4010
    expect(out[2].structure).toBe("Sell 4050P/4210C  |  Buy 4010P/4250C");
  });

  it("Long Call Butterfly: wings ±1%, body ATM ×2", () => {
    expect(out[3].structure).toBe("Buy 4090C / Sell 2×4130C / Buy 4170C");
  });

  it("Long Put Butterfly mirrors the call butterfly", () => {
    expect(out[4].structure).toBe("Buy 4170P / Sell 2×4130P / Buy 4090P");
  });

  it("Long Straddle buys ATM call + put", () => {
    expect(out[5].structure).toBe("Buy 4130C + 4130P");
  });

  it("Long Strangle buys ±1.5% OTM", () => {
    expect(out[6].structure).toBe("Buy 4190C + 4070P");
  });

  it("nearest() snaps to an existing strike; BCS cost is a positive number", () => {
    // callNis: 4130→180 (3.6 pts), 4160→150 (3.0 pts) → cost 0.6
    expect(typeof out[1].costPts).toBe("number");
    expect(out[1].costPts).toBeCloseTo(0.6, 6);
  });

  it("nearest() returns (target, 0) when a side has no priced strike", () => {
    // all puts 0 → straddle put leg contributes 0 pts, but strikes still resolve
    const noPuts: ChainRow[] = chain.map((r) => ({ ...r, putNis: 0 }));
    const o = strategyBuilder(4130, noPuts);
    expect(o[5].structure).toBe("Buy 4130C + 4130P");
  });
});
