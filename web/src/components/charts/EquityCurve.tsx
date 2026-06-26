import { ils } from "@/lib/format";
import { SvgChart } from "@/components/charts/SvgChart";

export function EquityCurve({
  points,
  initial,
}: {
  points: { label: string; value: number }[];
  initial: number;
}) {
  const W = 720, H = 320, pad = { t: 24, r: 20, b: 36, l: 64 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const vals = points.map((p) => p.value);
  const lo = Math.min(...vals, initial), hi = Math.max(...vals, initial);
  const gap = (hi - lo) * 0.12 || 1;
  const yMin = lo - gap, yMax = hi + gap;
  const sx = (i: number) => pad.l + (i / (points.length - 1)) * iw;
  const sy = (v: number) => pad.t + ih - ((v - yMin) / (yMax - yMin)) * ih;
  const final = vals[vals.length - 1];
  const up = final >= initial;
  const color = up ? "var(--color-pos)" : "var(--color-neg)";
  const linePts = points.map((p, i) => `${sx(i).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ");
  const areaPts = `${pad.l},${pad.t + ih} ${linePts} ${pad.l + iw},${pad.t + ih}`;
  const yTicks = [yMin, (yMin + yMax) / 2, yMax];
  const money = (v: number) => ils(v);
  const xEvery = Math.ceil(points.length / 6);
  return (
    <SvgChart w={W} h={H} label="עקומת שווי התיק לאורך זמן">
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={pad.l} y1={sy(t)} x2={W - pad.r} y2={sy(t)} stroke="var(--color-grid)" />
            <text x={pad.l - 8} y={sy(t) + 3} textAnchor="end" fontSize="10" fill="var(--color-text3)">{money(t)}</text>
          </g>
        ))}
        {/* baseline = initial */}
        <line x1={pad.l} y1={sy(initial)} x2={W - pad.r} y2={sy(initial)} stroke="var(--color-text3)" strokeWidth="1" strokeDasharray="4 4" />
        <text x={pad.l + 4} y={sy(initial) - 4} fontSize="9" fill="var(--color-text3)">הון התחלתי {money(initial)}</text>
        {/* area + line */}
        <polygon points={areaPts} fill={color} opacity="0.10" />
        <polyline points={linePts} fill="none" stroke={color} strokeWidth="2" />
        {/* final point */}
        <circle cx={sx(points.length - 1)} cy={sy(final)} r="4" fill={color} />
        <text x={sx(points.length - 1) - 6} y={sy(final) - 8} textAnchor="end" fontSize="11" fontWeight="700" fill={color}>{money(final)}</text>
        {/* x labels */}
        {points.map((p, i) =>
          i % xEvery === 0 ? (
            <text key={i} x={sx(i)} y={H - pad.b + 16} textAnchor="middle" fontSize="9" fill="var(--color-text3)">{p.label}</text>
          ) : null
        )}
    </SvgChart>
  );
}
