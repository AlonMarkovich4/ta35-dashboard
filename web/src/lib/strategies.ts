// תורגם 1:1 מ-src/strategies.py + src/backtester.py — אין לשנות נוסחאות.

export type Params = Record<string, number>;

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const BCS_FULL_UP_PCT = 1.0; // _BCS_FULL_UP_PCT

export type StrategyDef = {
  id: number;
  name: string;
  isSuccess: (move: number, p: Params) => boolean;
  intensity: (move: number, p: Params) => number;
};

export const STRATEGIES: StrategyDef[] = [
  {
    id: 1,
    name: "Bull Call Spread",
    isSuccess: (m) => m > 0,
    intensity: (m) => (m <= 0 ? 0 : clamp01(m / BCS_FULL_UP_PCT)),
  },
  {
    id: 2,
    name: "Short Iron Condor",
    isSuccess: (m, p) => Math.abs(m) < p.width_pct,
    intensity: (m, p) =>
      p.width_pct <= 0 ? (m === 0 ? 1 : 0) : clamp01(1 - Math.abs(m) / p.width_pct),
  },
  {
    id: 3,
    name: "Long Call Butterfly",
    isSuccess: (m, p) => Math.abs(m) < p.wing_pct,
    intensity: (m, p) =>
      p.wing_pct <= 0 ? (m === 0 ? 1 : 0) : clamp01(1 - Math.abs(m) / p.wing_pct),
  },
  {
    id: 4,
    name: "Long Put Butterfly",
    isSuccess: (m, p) => Math.abs(m) < p.wing_pct,
    intensity: (m, p) =>
      p.wing_pct <= 0 ? (m === 0 ? 1 : 0) : clamp01(1 - Math.abs(m) / p.wing_pct),
  },
  {
    id: 5,
    name: "Long Straddle",
    isSuccess: (m, p) => Math.abs(m) > p.min_move_pct,
    intensity: (m, p) =>
      p.min_move_pct <= 0
        ? (Math.abs(m) > 0 ? 1 : 0)
        : clamp01((Math.abs(m) - p.min_move_pct) / p.min_move_pct), // 1.0 ב-2m
  },
  {
    id: 6,
    name: "Long Strangle",
    isSuccess: (m, p) => Math.abs(m) > p.min_move_pct,
    intensity: (m, p) =>
      p.min_move_pct <= 0
        ? (Math.abs(m) > 0 ? 1 : 0)
        : clamp01((Math.abs(m) - p.min_move_pct) / (1.5 * p.min_move_pct)), // 1.0 ב-2.5m
  },
];

export const STRATEGY_GRID: Record<number, Params[]> = {
  1: [10, 20, 30, 50].map((w) => ({ width_pts: w })),
  2: [1.0, 1.5, 2.0, 2.5, 3.0].map((w) => ({ width_pct: w })),
  3: [0.5, 1.0, 1.5, 2.0].map((w) => ({ wing_pct: w })),
  4: [0.5, 1.0, 1.5, 2.0].map((w) => ({ wing_pct: w })),
  5: [0.5, 1.0, 1.5, 2.0].map((m) => ({ min_move_pct: m })),
  6: [0.5, 1.0, 1.5, 2.0].map((m) => ({ min_move_pct: m })),
};

const PARAM_LABELS: Record<string, [string, string]> = {
  width_pts: ["רוחב", "נק'"],
  width_pct: ["טווח", "%"],
  wing_pct: ["כנף", "%"],
  min_move_pct: ["סף תנועה", "%"],
};

export function fmtParams(p: Params): string {
  return Object.entries(p)
    .map(([k, v]) => {
      const [label, unit] = PARAM_LABELS[k] ?? [k, ""];
      const val = Number.isInteger(v) ? String(v) : String(v);
      return `${label}=${val}${unit}`;
    })
    .join(", ");
}

export type VariantResult = {
  strategyId: number;
  strategyName: string;
  paramsRepr: string;
  paramValue: number;
  winRate: number; // [0,1]
  wins: number;
  losses: number;
  total: number;
  avgIntensity: number;
};

// שקילות מלאה ל-run_backtest (הסינון נעשה ע"י הקורא — מקבל moves מסוננים)
export function runBacktest(moves: number[]): VariantResult[] {
  const total = moves.length;
  const rows: VariantResult[] = [];
  for (const s of STRATEGIES) {
    for (const params of STRATEGY_GRID[s.id]) {
      let wins = 0;
      let intensitySum = 0;
      for (const m of moves) {
        if (s.isSuccess(m, params)) wins++;
        intensitySum += s.intensity(m, params);
      }
      rows.push({
        strategyId: s.id,
        strategyName: s.name,
        paramsRepr: fmtParams(params),
        paramValue: Object.values(params)[0] ?? 0,
        winRate: total ? wins / total : 0,
        wins,
        losses: total - wins,
        total,
        avgIntensity: total ? intensitySum / total : 0,
      });
    }
  }
  return rows;
}

// שקילות ל-best_per_strategy: הווריאנט עם WR הגבוה לכל אסטרטגיה; שוויון → הראשון (השמרני); ממוין WR יורד
export function bestPerStrategy(results: VariantResult[]): VariantResult[] {
  const best = new Map<number, VariantResult>();
  for (const r of results) {
    const cur = best.get(r.strategyId);
    if (!cur || r.winRate > cur.winRate) best.set(r.strategyId, r);
  }
  return [...best.values()].sort((a, b) => b.winRate - a.winRate);
}
