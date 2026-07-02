"use client";

import { useState, useMemo, type ReactNode } from "react";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { FilterRow } from "@/components/ui/FilterRow";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Empty } from "@/components/ui/Empty";
import { SvgChart } from "@/components/charts/SvgChart";
import type { HistoricalData } from "@/lib/data";

// מיפוי סוג פקיעה גולמי → תווית
const typeLabel = (t: string) => (t === "M" ? "חודשי (M)" : t === "W" ? "שבועי (W)" : t);

// ─── Charts (SVG, CSS vars) ─────────────────────────────────────────
function Histogram({ bins }: { bins: { c: number; n: number }[] }) {
  const W = 720, H = 300, pad = { t: 16, r: 16, b: 34, l: 44 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const nMax = Math.max(1, ...bins.map((b) => b.n));
  const bw = iw / Math.max(1, bins.length);
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
  const maxAbs = Math.max(0.01, ...data.map((d) => Math.abs(d.avg))) * 1.2;
  const bw = iw / Math.max(1, data.length);
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
  const lo = Math.min(0, ...data.map((d) => d.min));
  const hi = Math.max(0, ...data.map((d) => d.max));
  const span = hi - lo || 1;
  const bw = iw / Math.max(1, data.length);
  const sy = (v: number) => pad.t + ih - ((v - lo) / span) * ih;
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

// ─── View ───────────────────────────────────────────────────────────
const TYPE_OPTS = [
  { v: "all", l: "הכל" },
  { v: "W", l: "שבועי (W)" },
  { v: "M", l: "חודשי (M)" },
] as const;
type TypeV = (typeof TYPE_OPTS)[number]["v"];

export function HistoricalView({ data }: { data: HistoricalData }) {
  const { aggs, bins, medians, medianAllAbs } = data;
  const [type, setType] = useState<TypeV>("all");

  const view = useMemo(() => {
    const sel = type === "all" ? aggs : aggs.filter((a) => a.type === type);

    // summary
    const total = sel.reduce((s, a) => s + a.count, 0);
    const ups = sel.reduce((s, a) => s + a.ups, 0);
    const downs = sel.reduce((s, a) => s + a.downs, 0);
    const sumAbs = sel.reduce((s, a) => s + a.sumAbs, 0);
    const summary = {
      total,
      up: total ? (ups / total) * 100 : 0,
      down: total ? (downs / total) * 100 : 0,
      avgAbs: total ? sumAbs / total : 0,
      medAbs: type === "all" ? medianAllAbs : medians.find((m) => m.type === type)?.medianAbs ?? 0,
    };

    // histogram — combine bins by center for the selected scope
    const binMap = new Map<number, number>();
    (type === "all" ? bins : bins.filter((b) => b.type === type)).forEach((b) =>
      binMap.set(b.center, (binMap.get(b.center) ?? 0) + b.n),
    );
    const hist = [...binMap.entries()]
      .map(([c, n]) => ({ c, n }))
      .sort((a, b) => a.c - b.c);

    // yearly — group selected aggs by year
    const yearMap = new Map<number, { count: number; sumMove: number; min: number; max: number }>();
    for (const a of sel) {
      const y = yearMap.get(a.year) ?? { count: 0, sumMove: 0, min: Infinity, max: -Infinity };
      y.count += a.count;
      y.sumMove += a.sumMove;
      y.min = Math.min(y.min, a.minMove);
      y.max = Math.max(y.max, a.maxMove);
      yearMap.set(a.year, y);
    }
    const yearly = [...yearMap.entries()]
      .map(([year, y]) => ({
        year,
        avg: y.count ? y.sumMove / y.count : 0,
        min: y.min === Infinity ? 0 : y.min,
        max: y.max === -Infinity ? 0 : y.max,
      }))
      .sort((a, b) => a.year - b.year);

    // breakdown by type (respects the filter)
    const typesToShow =
      type === "all" ? [...new Set(aggs.map((a) => a.type))].sort() : [type];
    const breakdown = typesToShow.map((t) => {
      const rows = aggs.filter((a) => a.type === t);
      const count = rows.reduce((s, a) => s + a.count, 0);
      const sumMove = rows.reduce((s, a) => s + a.sumMove, 0);
      const sAbs = rows.reduce((s, a) => s + a.sumAbs, 0);
      const u = rows.reduce((s, a) => s + a.ups, 0);
      const d = rows.reduce((s, a) => s + a.downs, 0);
      return {
        type: typeLabel(t),
        count,
        avg: count ? sumMove / count : 0,
        absAvg: count ? sAbs / count : 0,
        absMed: medians.find((m) => m.type === t)?.medianAbs ?? 0,
        up: count ? (u / count) * 100 : 0,
        down: count ? (d / count) * 100 : 0,
        max: rows.length ? Math.max(...rows.map((a) => a.maxMove)) : 0,
        min: rows.length ? Math.min(...rows.map((a) => a.minMove)) : 0,
      };
    });

    const years = aggs.map((a) => a.year);
    const yearRange = years.length ? `${Math.min(...years)}–${Math.max(...years)}` : "—";

    return { summary, hist, yearly, breakdown, yearRange };
  }, [type, aggs, bins, medians, medianAllAbs]);

  if (aggs.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">ניתוח היסטורי</h1>
        </div>
        <Empty title="אין נתוני פקיעות היסטוריים" />
      </div>
    );
  }

  const { summary, hist, yearly, breakdown, yearRange } = view;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">ניתוח היסטורי</h1>
        <p className="mt-1 text-sm text-text2">
          ניתוח סטטיסטי של פקיעות מדד TA-35 בין השנים {yearRange}.
        </p>
      </div>

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <FilterRow
            options={TYPE_OPTS.map((o) => ({ v: o.v, l: o.l }))}
            value={type}
            onPick={(v) => setType(v as TypeV)}
          />
          <div className="text-xs text-text3">טווח שנים: {yearRange}</div>
        </div>
      </Panel>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi label="סה״כ פקיעות" value={String(summary.total)} />
        <Kpi label="עליות" value={`${summary.up.toFixed(1)}%`} tone="text-pos" />
        <Kpi label="ירידות" value={`${summary.down.toFixed(1)}%`} tone="text-neg" />
        <Kpi label="תנועה ממוצעת" value={`${summary.avgAbs.toFixed(2)}%`} />
        <Kpi label="חציון תנועה" value={`${summary.medAbs.toFixed(2)}%`} />
      </div>

      <Panel title="התפלגות תנועות פקיעה" sub="ירוק = עלייה · אדום = ירידה">
        <Histogram bins={hist} />
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
              {breakdown.map((r) => (
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
                  <td className="py-2.5 tabular-nums text-pos" dir="ltr">{r.max >= 0 ? "+" : ""}{r.max.toFixed(1)}%</td>
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
            { label: "ממוצע שנתי", content: <YearlyAvg data={yearly} /> },
            { label: "התפלגות שנתית", content: <YearlyRange data={yearly} /> },
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
