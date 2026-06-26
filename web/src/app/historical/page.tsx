"use client";

import { useState, type ReactNode } from "react";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { FilterRow } from "@/components/ui/FilterRow";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SvgChart } from "@/components/charts/SvgChart";

// ─── Mock (נאמן-צורה; יוחלף ב-Supabase בשלב 4) ──────────────────────
const SUMMARY = { total: "965", up: "58.3%", down: "41.7%", avgAbs: "0.94%", medAbs: "0.71%" };

// היסטוגרמה: מרכז בין (%), מספר פקיעות
const HIST: { c: number; n: number }[] = [
  { c: -4.75, n: 3 }, { c: -4.25, n: 5 }, { c: -3.75, n: 8 }, { c: -3.25, n: 13 },
  { c: -2.75, n: 20 }, { c: -2.25, n: 31 }, { c: -1.75, n: 46 }, { c: -1.25, n: 63 },
  { c: -0.75, n: 80 }, { c: -0.25, n: 92 },
  { c: 0.25, n: 98 }, { c: 0.75, n: 88 }, { c: 1.25, n: 70 }, { c: 1.75, n: 52 },
  { c: 2.25, n: 36 }, { c: 2.75, n: 24 }, { c: 3.25, n: 15 }, { c: 3.75, n: 9 },
  { c: 4.25, n: 6 }, { c: 4.75, n: 4 },
];

const BREAKDOWN = [
  { type: "שבועי (W)", count: 720, avg: 0.18, absAvg: 0.82, absMed: 0.62, up: 57.8, down: 42.2, max: 6.9, min: -8.4 },
  { type: "חודשי (M)", count: 245, avg: 0.31, absAvg: 1.28, absMed: 1.05, up: 59.6, down: 40.4, max: 9.7, min: -12.1 },
];

const YEARLY = [
  { year: 2010, avg: 0.22, min: -4.1, max: 5.2 }, { year: 2011, avg: -0.35, min: -6.8, max: 4.0 },
  { year: 2012, avg: 0.41, min: -3.6, max: 5.9 }, { year: 2013, avg: 0.28, min: -3.1, max: 4.4 },
  { year: 2014, avg: 0.12, min: -3.9, max: 4.1 }, { year: 2015, avg: -0.18, min: -5.2, max: 4.8 },
  { year: 2016, avg: 0.33, min: -4.4, max: 5.5 }, { year: 2017, avg: 0.45, min: -2.8, max: 4.6 },
  { year: 2018, avg: -0.52, min: -7.1, max: 4.2 }, { year: 2019, avg: 0.61, min: -3.3, max: 6.1 },
  { year: 2020, avg: -0.74, min: -8.4, max: 7.3 }, { year: 2021, avg: 0.58, min: -3.0, max: 5.7 },
  { year: 2022, avg: -0.41, min: -6.2, max: 5.0 }, { year: 2023, avg: 0.29, min: -4.0, max: 4.9 },
  { year: 2024, avg: 0.66, min: -5.5, max: 9.7 }, { year: 2025, avg: 0.38, min: -4.7, max: 6.3 },
  { year: 2026, avg: 0.24, min: -3.2, max: 4.1 },
];

// ─── Charts (SVG, CSS vars) ─────────────────────────────────────────
function Histogram({ bins }: { bins: { c: number; n: number }[] }) {
  const W = 720, H = 300, pad = { t: 16, r: 16, b: 34, l: 44 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const nMax = Math.max(...bins.map((b) => b.n));
  const bw = iw / bins.length;
  const zeroX = pad.l + bins.filter((b) => b.c < 0).length * bw;
  const yTicks = [0, Math.round(nMax / 2), nMax];
  const sy = (n: number) => pad.t + ih - (n / nMax) * ih;
  return (
    <SvgChart w={W} h={H} label="התפלגות תנועות פקיעה לפי אחוז תנועה">
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={pad.l} y1={sy(t)} x2={W - pad.r} y2={sy(t)} stroke="var(--color-grid)" />
          <text x={pad.l - 8} y={sy(t) + 3} textAnchor="end" fontSize="10" fill="var(--color-text3)">{t}</text>
        </g>
      ))}
      {bins.map((b, i) => {
        const h = (b.n / nMax) * ih;
        return (
          <rect key={i} x={pad.l + i * bw + 1} y={pad.t + ih - h} width={bw - 2} height={h}
            fill={b.c >= 0 ? "var(--color-pos)" : "var(--color-neg)"} opacity="0.85" rx="1" />
        );
      })}
      <line x1={zeroX} y1={pad.t} x2={zeroX} y2={pad.t + ih} stroke="var(--color-text3)" strokeWidth="1.5" strokeDasharray="4 4" />
      <text x={zeroX + 4} y={pad.t + 10} fontSize="10" fill="var(--color-text2)">0%</text>
      {bins.map((b, i) =>
        i % 4 === 0 ? (
          <text key={`x${i}`} x={pad.l + i * bw + bw / 2} y={H - pad.b + 16} textAnchor="middle" fontSize="9" fill="var(--color-text3)">
            {b.c > 0 ? "+" : ""}{b.c}
          </text>
        ) : null
      )}
    </SvgChart>
  );
}

function YearlyAvg({ data }: { data: { year: number; avg: number }[] }) {
  const W = 720, H = 320, pad = { t: 24, r: 16, b: 46, l: 44 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const maxAbs = Math.max(...data.map((d) => Math.abs(d.avg))) * 1.2;
  const bw = iw / data.length;
  const baseY = pad.t + ih / 2;
  const scale = (v: number) => (v / maxAbs) * (ih / 2);
  return (
    <SvgChart w={W} h={H} label="תנועה ממוצעת לפי שנה">
      <line x1={pad.l} y1={baseY} x2={W - pad.r} y2={baseY} stroke="var(--color-text3)" strokeDasharray="3 3" />
      {data.map((d, i) => {
        const x = pad.l + i * bw;
        const h = Math.abs(scale(d.avg));
        const up = d.avg >= 0;
        const y = up ? baseY - h : baseY;
        const cx = x + bw / 2;
        return (
          <g key={d.year}>
            <rect x={x + 4} y={y} width={bw - 8} height={h} rx="2"
              fill={up ? "var(--color-pos)" : "var(--color-neg)"} opacity="0.85" />
            <text x={cx} y={up ? y - 4 : y + h + 11} textAnchor="middle" fontSize="8"
              fill={up ? "var(--color-pos)" : "var(--color-neg)"}>
              {d.avg > 0 ? "+" : ""}{d.avg.toFixed(2)}
            </text>
            <text x={cx} y={H - pad.b + 16} textAnchor="middle" fontSize="9" fill="var(--color-text3)"
              transform={`rotate(-45 ${cx} ${H - pad.b + 16})`}>{d.year}</text>
          </g>
        );
      })}
    </SvgChart>
  );
}

function YearlyRange({ data }: { data: { year: number; min: number; max: number; avg: number }[] }) {
  const W = 720, H = 320, pad = { t: 20, r: 16, b: 46, l: 44 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const lo = Math.min(...data.map((d) => d.min));
  const hi = Math.max(...data.map((d) => d.max));
  const bw = iw / data.length;
  const sy = (v: number) => pad.t + ih - ((v - lo) / (hi - lo)) * ih;
  const yTicks = [Math.ceil(lo), 0, Math.floor(hi)];
  return (
    <SvgChart w={W} h={H} label="טווח תנועות שנתי — מינימום, מקסימום וממוצע">
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={pad.l} y1={sy(t)} x2={W - pad.r} y2={sy(t)} stroke="var(--color-grid)" />
          <text x={pad.l - 8} y={sy(t) + 3} textAnchor="end" fontSize="10" fill="var(--color-text3)">
            {t > 0 ? "+" : ""}{t}
          </text>
        </g>
      ))}
      <line x1={pad.l} y1={sy(0)} x2={W - pad.r} y2={sy(0)} stroke="var(--color-text3)" strokeDasharray="3 3" />
      {data.map((d, i) => {
        const x = pad.l + i * bw + bw / 2;
        return (
          <g key={d.year}>
            <line x1={x} y1={sy(d.max)} x2={x} y2={sy(d.min)} stroke="var(--color-accent2)" strokeWidth="2" strokeLinecap="round" />
            <circle cx={x} cy={sy(d.avg)} r="3" fill={d.avg >= 0 ? "var(--color-pos)" : "var(--color-neg)"} />
            <text x={x} y={H - pad.b + 16} textAnchor="middle" fontSize="9" fill="var(--color-text3)"
              transform={`rotate(-45 ${x} ${H - pad.b + 16})`}>{d.year}</text>
          </g>
        );
      })}
    </SvgChart>
  );
}

function Tabs({ tabs }: { tabs: { label: string; content: ReactNode }[] }) {
  const [i, setI] = useState(0);
  return (
    <div>
      <div className="mb-4 flex gap-2 border-b border-border">
        {tabs.map((t, idx) => (
          <button key={idx} onClick={() => setI(idx)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
              i === idx ? "border-accent text-accent" : "border-transparent text-text3 hover:text-text1"
            }`}>
            {t.label}
          </button>
        ))}
      </div>
      <div>{tabs[i].content}</div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────
const TYPE_OPTS = [
  { v: "all", l: "הכל" },
  { v: "W", l: "שבועי (W)" },
  { v: "M", l: "חודשי (M)" },
] as const;
type TypeV = (typeof TYPE_OPTS)[number]["v"];

export default function HistoricalPage() {
  const [type, setType] = useState<TypeV>("all");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">ניתוח היסטורי</h1>
        <p className="mt-1 text-sm text-text2">
          ניתוח סטטיסטי של 965+ פקיעות מדד TA-35 בין השנים 2010–2026.
        </p>
      </div>

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <FilterRow
            options={TYPE_OPTS.map((o) => ({ v: o.v, l: o.l }))}
            value={type}
            onPick={(v) => setType(v as TypeV)}
          />
          <div className="text-xs text-text3">טווח שנים: 2010–2026</div>
        </div>
      </Panel>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi label="סה״כ פקיעות" value={SUMMARY.total} />
        <Kpi label="עליות" value={SUMMARY.up} tone="text-pos" />
        <Kpi label="ירידות" value={SUMMARY.down} tone="text-neg" />
        <Kpi label="תנועה ממוצעת" value={SUMMARY.avgAbs} />
        <Kpi label="חציון תנועה" value={SUMMARY.medAbs} />
      </div>

      <Panel title="התפלגות תנועות פקיעה" sub="ירוק = עלייה · אדום = ירידה">
        <Histogram bins={HIST} />
      </Panel>

      <Panel title="פירוט לפי סוג פקיעה">
        <div className="overflow-x-auto">
          <table className="w-full text-right text-sm">
            <thead>
              <tr className="text-xs text-text3">
                <th className="pb-2 font-medium">סוג</th>
                <th className="pb-2 font-medium">פקיעות</th>
                <th className="pb-2 font-medium">ממוצע תנועה</th>
                <th className="pb-2 font-medium">ממוצע מוחלט</th>
                <th className="pb-2 font-medium">חציון מוחלט</th>
                <th className="pb-2 font-medium">% עליות</th>
                <th className="pb-2 font-medium">% ירידות</th>
                <th className="pb-2 font-medium">מקס</th>
                <th className="pb-2 font-medium">מין</th>
              </tr>
            </thead>
            <tbody>
              {BREAKDOWN.map((r) => (
                <tr key={r.type} className="border-t border-border">
                  <td className="py-2.5 font-medium">{r.type}</td>
                  <td className="py-2.5 tabular-nums text-text2">{r.count}</td>
                  <td className={`py-2.5 tabular-nums ${r.avg >= 0 ? "text-pos" : "text-neg"}`} dir="ltr">
                    {r.avg > 0 ? "+" : ""}{r.avg.toFixed(2)}%
                  </td>
                  <td className="py-2.5 tabular-nums text-text2">{r.absAvg.toFixed(2)}%</td>
                  <td className="py-2.5 tabular-nums text-text2">{r.absMed.toFixed(2)}%</td>
                  <td className="py-2.5 tabular-nums text-pos">{r.up.toFixed(1)}%</td>
                  <td className="py-2.5 tabular-nums text-neg">{r.down.toFixed(1)}%</td>
                  <td className="py-2.5 tabular-nums text-pos" dir="ltr">+{r.max.toFixed(1)}%</td>
                  <td className="py-2.5 tabular-nums text-neg" dir="ltr">{r.min.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="תנועות לפי שנה">
        <Tabs
          tabs={[
            { label: "ממוצע שנתי", content: <YearlyAvg data={YEARLY} /> },
            { label: "התפלגות שנתית", content: <YearlyRange data={YEARLY} /> },
          ]}
        />
      </Panel>

      <Disclaimer>
        כלי מחקר בלבד. הנתונים לניתוח סטטיסטי היסטורי בלבד ואינם המלצת מסחר, ייעוץ
        השקעות או תחזית. מסחר באופציות כרוך בסיכון של אובדן מלא.
      </Disclaimer>
    </div>
  );
}
