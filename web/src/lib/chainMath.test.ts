import { describe, it, expect } from "vitest";
import { findAtm, type AtmInput } from "@/lib/chainMath";

const row = (strike: number, callNis: number, putNis: number, callDelta = 0): AtmInput => ({
  strike,
  callNis,
  putNis,
  callDelta,
});

describe("findAtm", () => {
  it("uses put-call parity (min |call-put|) for the ATM strike", () => {
    const { atmStrike, indexEstimate } = findAtm([
      row(4120, 600, 400), // |diff| 200
      row(4130, 500, 500), // |diff| 0 → ATM
      row(4140, 400, 600), // |diff| 200
    ]);
    expect(atmStrike).toBe(4130);
    expect(indexEstimate).toBeCloseTo(4130, 6); // strike + (500-500)/50
  });

  it("estimates index = strike + (call-put)/50 at the parity strike", () => {
    const { atmStrike, indexEstimate } = findAtm([
      row(4130, 446, 618), // |diff| 172 → ATM
      row(4120, 783, 438), // |diff| 345
    ]);
    expect(atmStrike).toBe(4130);
    expect(indexEstimate).toBeCloseTo(4126.56, 2); // 4130 + (446-618)/50
  });

  it("falls back to delta≈0.5 when no strike has both sides priced", () => {
    const { atmStrike, indexEstimate } = findAtm([
      row(4100, 10, 0, 0.7),
      row(4130, 5, 0, 0.5),
      row(4160, 2, 0, 0.3),
    ]);
    expect(atmStrike).toBe(4130);
    expect(indexEstimate).toBe(4130);
  });

  it("falls back to mean strike (atmStrike null) with no parity and no positive delta", () => {
    const { atmStrike, indexEstimate } = findAtm([row(4000, 0, 0, 0), row(4200, 0, 0, 0)]);
    expect(atmStrike).toBeNull();
    expect(indexEstimate).toBe(4100);
  });

  it("returns nulls for empty input", () => {
    expect(findAtm([])).toEqual({ atmStrike: null, indexEstimate: null });
  });
});
