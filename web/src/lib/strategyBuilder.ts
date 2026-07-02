// תורגם 1:1 מ-src/options_parser.py :: get_strategy_strikes — אין לשנות נוסחאות.
import type { ChainRow } from "@/lib/data";

const MULTIPLIER = 50; // ₪ לנקודה

export type StrategyStrikes = {
  strikesDesc: string;
  structure: string;
  costPts: number;
  maxLossDesc: string;
  maxProfitDesc: string;
};

const f0 = (x: number) => x.toFixed(0);
const f1 = (x: number) => x.toFixed(1);
const nis = (pts: number) =>
  (pts * MULTIPLIER).toLocaleString("en-US", { maximumFractionDigits: 0 });
const r1 = (x: number) => Math.round(x * 10) / 10;

// chain — שרשרת מפורסרת (strike, callNis=call_price ₪, putNis=put_price ₪).
export function strategyBuilder(
  atmStrike: number,
  chain: ChainRow[],
): Record<number, StrategyStrikes> {
  // (actual_strike, price_in_pts) הקרוב ביותר לסטרייק יעד; מסנן price>0
  const nearest = (target: number, side: "call" | "put"): [number, number] => {
    const sub = chain.filter((r) => (side === "call" ? r.callNis : r.putNis) > 0);
    if (!sub.length) return [target, 0];
    let best = sub[0];
    for (const r of sub) {
      if (Math.abs(r.strike - target) < Math.abs(best.strike - target)) best = r;
    }
    const price = side === "call" ? best.callNis : best.putNis;
    return [best.strike, price / MULTIPLIER];
  };

  const [atmCStrike, atmCPts] = nearest(atmStrike, "call");
  const [atmPStrike, atmPPts] = nearest(atmStrike, "put");

  const pctStrike = (pct: number) => Math.round((atmStrike * (1 + pct / 100)) / 10) * 10;

  const out: Record<number, StrategyStrikes> = {};

  // 1 — Bull Call Spread (width=30pts)
  const width = 30;
  const [sellCStrike, sellCPts] = nearest(atmStrike + width, "call");
  const cost = atmCPts - sellCPts;
  out[1] = {
    strikesDesc: `קנה Call ${f0(atmCStrike)} | מכור Call ${f0(sellCStrike)}`,
    structure: `Buy ${f0(atmCStrike)}C / Sell ${f0(sellCStrike)}C`,
    costPts: r1(cost),
    maxLossDesc: `פרמיה נטו: ${f1(cost)} נק' = ${nis(cost)} ₪`,
    maxProfitDesc: `רוחב: ${width} נק' − פרמיה = ${f1(width - cost)} נק' = ${nis(width - cost)} ₪`,
  };

  // 2 — Short Iron Condor (width=2%)
  const sc = pctStrike(2.0), sp = pctStrike(-2.0);
  const wc = pctStrike(3.0), wp = pctStrike(-3.0);
  const [, scPts] = nearest(sc, "call");
  const [, spPts] = nearest(sp, "put");
  const [, wcPts] = nearest(wc, "call");
  const [, wpPts] = nearest(wp, "put");
  const premium = scPts + spPts - (wcPts + wpPts);
  out[2] = {
    strikesDesc: `מכור Put ${f0(sp)} / מכור Call ${f0(sc)} | קנה Put ${f0(wp)} / קנה Call ${f0(wc)}`,
    structure: `Sell ${f0(sp)}P/${f0(sc)}C  |  Buy ${f0(wp)}P/${f0(wc)}C`,
    costPts: r1(-premium),
    maxLossDesc: `רוחב כנף − פרמיה = ${f1(sp - wp - premium)} נק'`,
    maxProfitDesc: `פרמיה נטו: ${f1(premium)} נק' = ${nis(premium)} ₪`,
  };

  // 3 — Long Call Butterfly (wing=1%)
  const wingC = pctStrike(1.0), wingPC = pctStrike(-1.0);
  const [, loC] = nearest(wingPC, "call");
  const [, hiC] = nearest(wingC, "call");
  const costBf = loC + hiC - 2 * atmCPts;
  out[3] = {
    strikesDesc: `קנה Call ${f0(wingPC)} | מכור 2× Call ${f0(atmCStrike)} | קנה Call ${f0(wingC)}`,
    structure: `Buy ${f0(wingPC)}C / Sell 2×${f0(atmCStrike)}C / Buy ${f0(wingC)}C`,
    costPts: r1(costBf),
    maxLossDesc: `פרמיה נטו: ${f1(costBf)} נק' = ${nis(costBf)} ₪`,
    maxProfitDesc: `כנף − פרמיה: ${f1(wingC - atmCStrike - costBf)} נק'`,
  };

  // 4 — Long Put Butterfly (wing=1%)
  const [, loP] = nearest(wingC, "put");
  const [, hiP] = nearest(wingPC, "put");
  const costPb = loP + hiP - 2 * atmPPts;
  out[4] = {
    strikesDesc: `קנה Put ${f0(wingC)} | מכור 2× Put ${f0(atmPStrike)} | קנה Put ${f0(wingPC)}`,
    structure: `Buy ${f0(wingC)}P / Sell 2×${f0(atmPStrike)}P / Buy ${f0(wingPC)}P`,
    costPts: r1(costPb),
    maxLossDesc: `פרמיה נטו: ${f1(costPb)} נק' = ${nis(costPb)} ₪`,
    maxProfitDesc: `כנף − פרמיה: ${f1(atmPStrike - wingPC - costPb)} נק'`,
  };

  // 5 — Long Straddle
  const straddleCost = atmCPts + atmPPts;
  out[5] = {
    strikesDesc: `קנה Call ${f0(atmCStrike)} + Put ${f0(atmPStrike)}`,
    structure: `Buy ${f0(atmCStrike)}C + ${f0(atmPStrike)}P`,
    costPts: r1(straddleCost),
    maxLossDesc: `פרמיה: ${f1(straddleCost)} נק' = ${nis(straddleCost)} ₪`,
    maxProfitDesc: "בלתי מוגבל (לכל כיוון)",
  };

  // 6 — Long Strangle (1.5% OTM each side)
  const otmC = pctStrike(1.5), otmP = pctStrike(-1.5);
  const [, otmCPts] = nearest(otmC, "call");
  const [, otmPPts] = nearest(otmP, "put");
  const strangleCost = otmCPts + otmPPts;
  out[6] = {
    strikesDesc: `קנה Call ${f0(otmC)} + Put ${f0(otmP)} (OTM ×1.5%)`,
    structure: `Buy ${f0(otmC)}C + ${f0(otmP)}P`,
    costPts: r1(strangleCost),
    maxLossDesc: `פרמיה: ${f1(strangleCost)} נק' = ${nis(strangleCost)} ₪`,
    maxProfitDesc: "בלתי מוגבל (לכל כיוון)",
  };

  return out;
}
