import { SvgChart } from "@/components/charts/SvgChart";
import { buildPayoffGeometry } from "@/lib/marginMath";
import { money, en, pct } from "@/lib/format";

// גרף Payoff של ה-Short Iron Condor (הטרפז) — כמו בפלטפורמות מסחר. הגיאומטריה הטהורה
// (קודקודים + breakevens) חיה ב-marginMath.buildPayoffGeometry (unit-tested); כאן רק
// ההמרה ל-SVG: מילוי ירוק ברווח (>0), אדום בהפסד (<0), סמן המדד, ותוויות ה-strikes/BE.
export function PayoffChart({
  longPutStrike,
  shortPutStrike,
  shortCallStrike,
  longCallStrike,
  netPremium,
  maxLoss,
  baseIndex,
  wingPct,
}: {
  longPutStrike: number | null;
  shortPutStrike: number | null;
  shortCallStrike: number | null;
  longCallStrike: number | null;
  netPremium: number | null;
  maxLoss: number | null;
  baseIndex: number | null;
  wingPct: number | null;
}) {
  const geo = buildPayoffGeometry({
    longPutStrike, shortPutStrike, shortCallStrike, longCallStrike, netPremium, maxLoss,
  });
  if (!geo) {
    return (
      <div className="rounded-lg border border-border bg-surface2/30 px-4 py-6 text-center text-xs text-text3">
        אין נתוני רגליים מלאים לגרף (המלצה ישנה ללא הגנות שמורות).
      </div>
    );
  }

  const W = 560, H = 240, pad = { t: 24, r: 24, b: 40, l: 68 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const yGap = (geo.yMax - geo.yMin) * 0.18 || 1;
  const yLo = geo.yMin - yGap, yHi = geo.yMax + yGap;
  const sx = (x: number) => pad.l + ((x - geo.xMin) / (geo.xMax - geo.xMin)) * iw;
  const sy = (y: number) => pad.t + ih - ((y - yLo) / (yHi - yLo)) * ih;

  const { longPut: LP, shortPut: SP, shortCall: SC, longCall: LC } = geo.strikes;
  const beD = geo.breakevenDown, beU = geo.breakevenUp, y0 = sy(0);
  const P = geo.netPremium, ML = geo.maxLoss;

  const poly = (pts: [number, number][]) =>
    pts.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(" ");

  const greenPts = poly([[beD, 0], [SP, P], [SC, P], [beU, 0]]);            // אזור רווח
  const redLeftPts = poly([[geo.xMin, 0], [geo.xMin, ML], [LP, ML], [beD, 0]]); // הפסד צד put
  const redRightPts = poly([[beU, 0], [LC, ML], [geo.xMax, ML], [geo.xMax, 0]]); // הפסד צד call
  const linePts = geo.line.map((p) => `${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");

  const strikeTicks: [string, number, string][] = [
    ["long put", LP, "var(--color-text3)"],
    ["short put", SP, "var(--color-text2)"],
    ["short call", SC, "var(--color-text2)"],
    ["long call", LC, "var(--color-text3)"],
  ];

  return (
    <div className="max-w-2xl">
      <SvgChart w={W} h={H} label="גרף Payoff של הטרפז (Short Iron Condor)" minW={480}>
        {/* y ticks: premium / 0 / maxLoss */}
        {[P, 0, ML].map((t) => (
          <g key={t}>
            <line x1={pad.l} y1={sy(t)} x2={W - pad.r} y2={sy(t)} stroke="var(--color-grid)" strokeWidth="0.5" />
            <text x={pad.l - 8} y={sy(t) + 3} textAnchor="end" fontSize="9" fill="var(--color-text3)">
              {money(t)}
            </text>
          </g>
        ))}

        {/* מילוי אזורי רווח/הפסד */}
        <polygon points={redLeftPts} fill="var(--color-neg)" opacity="0.13" />
        <polygon points={redRightPts} fill="var(--color-neg)" opacity="0.13" />
        <polygon points={greenPts} fill="var(--color-pos)" opacity="0.16" />

        {/* קו ה-0 המודגש + עקומת ה-payoff */}
        <line x1={pad.l} y1={y0} x2={W - pad.r} y2={y0} stroke="var(--color-text3)" strokeWidth="1" />
        <polyline points={linePts} fill="none" stroke="var(--color-text1)" strokeWidth="2" />

        {/* סמן המדד (base_index בזמן ההמלצה) */}
        {baseIndex != null && baseIndex >= geo.xMin && baseIndex <= geo.xMax && (
          <g>
            <line x1={sx(baseIndex)} y1={pad.t} x2={sx(baseIndex)} y2={pad.t + ih}
                  stroke="var(--color-accent)" strokeWidth="1.5" strokeDasharray="4 3" />
            <text x={sx(baseIndex)} y={pad.t - 8} textAnchor="middle" fontSize="10" fontWeight="700"
                  fill="var(--color-accent)">מדד {en(baseIndex)}</text>
          </g>
        )}

        {/* 4 ה-strikes על ציר X */}
        {strikeTicks.map(([lbl, k, color]) => (
          <g key={lbl}>
            <line x1={sx(k)} y1={pad.t + ih} x2={sx(k)} y2={pad.t + ih + 4} stroke={color} />
            <text x={sx(k)} y={H - pad.b + 16} textAnchor="middle" fontSize="9" fill={color}>{en(k)}</text>
          </g>
        ))}

        {/* breakevens על קו ה-0 */}
        {[beD, beU].map((be, i) => (
          <g key={i}>
            <circle cx={sx(be)} cy={y0} r="3" fill="var(--color-text2)" />
            <text x={sx(be)} y={y0 - 6} textAnchor="middle" fontSize="8.5" fill="var(--color-text3)">
              BE {en(be)}
            </text>
          </g>
        ))}

        {/* תוויות פרמיה / הפסד-מקס על המקטעים השטוחים */}
        <text x={sx((SP + SC) / 2)} y={sy(P) - 6} textAnchor="middle" fontSize="10" fontWeight="700"
              fill="var(--color-pos)">{money(P)}</text>
        <text x={sx((geo.xMin + LP) / 2)} y={sy(ML) - 6} textAnchor="middle" fontSize="10" fontWeight="700"
              fill="var(--color-neg)">{money(ML)}</text>
      </SvgChart>

      {/* legend/‏caption עם 4 הרגליים המדויקות (RTL) */}
      <div className="mt-1 text-[11px] text-text3" dir="rtl">
        <span className="text-text2">מכור:</span> {en(SP)}P / {en(SC)}C ·{" "}
        <span className="text-text2">קנה:</span> {en(LP)}P / {en(LC)}C ·{" "}
        BE {en(beD)}–{en(beU)} · כנף {pct(wingPct, 2)} ·{" "}
        <span className="text-pos">פרמיה {money(P)}</span> ·{" "}
        <span className="text-neg">הפסד-מקס {money(ML)}</span>
      </div>
    </div>
  );
}
