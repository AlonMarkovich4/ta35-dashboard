type Pt = { strike: number; call: number | null; put: number | null };

export function ChainChart({
  data,
  atm,
  index,
}: {
  data: Pt[];
  atm: number;
  index: number;
}) {
  const W = 720;
  const H = 360;
  const pad = { t: 28, r: 20, b: 40, l: 52 };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;

  const strikes = data.map((d) => d.strike);
  const xMin = Math.min(...strikes);
  const xMax = Math.max(...strikes);
  const yMax =
    Math.ceil(Math.max(...data.flatMap((d) => [d.call ?? 0, d.put ?? 0])) / 20) * 20;

  const sx = (s: number) => pad.l + ((s - xMin) / (xMax - xMin)) * iw;
  const sy = (v: number) => pad.t + ih - (v / yMax) * ih;

  const line = (key: "call" | "put") =>
    data
      .filter((d) => d[key] != null && (d[key] as number) > 0)
      .sort((a, b) => a.strike - b.strike)
      .map((d) => `${sx(d.strike).toFixed(1)},${sy(d[key] as number).toFixed(1)}`)
      .join(" ");

  const xTicks = data.filter((_, i) => i % 2 === 0).map((d) => d.strike);
  const yTicks = [0, yMax / 2, yMax];

  return (
    <div dir="ltr" className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[640px]" role="img">
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={pad.l} y1={sy(t)} x2={W - pad.r} y2={sy(t)} stroke="var(--color-grid)" strokeWidth="1" />
            <text x={pad.l - 8} y={sy(t) + 3} textAnchor="end" fontSize="10" fill="var(--color-text3)">
              {t}
            </text>
          </g>
        ))}

        {xTicks.map((t) => (
          <text key={t} x={sx(t)} y={H - pad.b + 16} textAnchor="middle" fontSize="10" fill="var(--color-text3)">
            {t.toLocaleString("en-US")}
          </text>
        ))}

        {/* ATM */}
        <line x1={sx(atm)} y1={pad.t} x2={sx(atm)} y2={pad.t + ih} stroke="var(--color-text3)" strokeWidth="1.5" strokeDasharray="5 4" />
        <text x={sx(atm) + 4} y={pad.t + 10} fontSize="10" fill="var(--color-text2)">
          ATM {atm.toLocaleString("en-US")}
        </text>

        {/* index estimate */}
        <line x1={sx(index)} y1={pad.t} x2={sx(index)} y2={pad.t + ih} stroke="var(--color-accent2)" strokeWidth="1" strokeDasharray="2 3" />

        {/* Call / Put */}
        <polyline points={line("call")} fill="none" stroke="var(--color-pos)" strokeWidth="2" />
        <polyline points={line("put")} fill="none" stroke="var(--color-neg)" strokeWidth="2" />

        {data.filter((d) => d.call != null && (d.call as number) > 0).map((d) => (
          <circle key={`c${d.strike}`} cx={sx(d.strike)} cy={sy(d.call as number)} r="2.6" fill="var(--color-pos)" />
        ))}
        {data.filter((d) => d.put != null && (d.put as number) > 0).map((d) => (
          <circle key={`p${d.strike}`} cx={sx(d.strike)} cy={sy(d.put as number)} r="2.6" fill="var(--color-neg)" />
        ))}

        {/* legend */}
        <rect x={pad.l} y={6} width="10" height="10" rx="2" fill="var(--color-pos)" />
        <text x={pad.l + 15} y={15} fontSize="11" fill="var(--color-text2)">Call</text>
        <rect x={pad.l + 56} y={6} width="10" height="10" rx="2" fill="var(--color-neg)" />
        <text x={pad.l + 71} y={15} fontSize="11" fill="var(--color-text2)">Put</text>
      </svg>
    </div>
  );
}
