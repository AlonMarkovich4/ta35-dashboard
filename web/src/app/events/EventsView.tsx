"use client";

import { useState } from "react";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SvgChart } from "@/components/charts/SvgChart";
import { Sprout, Refresh, Trash, Plus, Dot } from "@/components/icons";
import type {
  EventRow,
  Impact,
  TimelinePoint,
  CatRow,
  ExtremeRow,
} from "@/lib/data";

// ─── styling / static placeholders ─────────────────────────────────
const CAT_COLOR: Record<string, string> = {
  מלחמה: "var(--color-neg)",
  מגפה: "var(--color-purple)",
  ריבית: "var(--color-accent2)",
  משבר: "var(--color-warn)",
  פוליטי: "var(--color-pos)",
  אחר: "var(--color-text3)",
};

// חדשות מטלגרם — עדיין mock (RSS ייחובר בהמשך)
const TELEGRAM = [
  { date: "25/06/2026", cat: "ריבית", title: "בנק ישראל: הריבית נותרה ללא שינוי" },
  { date: "24/06/2026", cat: "משבר", title: "ירידות באירופה על רקע נתוני אינפלציה" },
  { date: "23/06/2026", cat: "אחר", title: "ת״א 35 ננעל ביציבות" },
  { date: "22/06/2026", cat: "מלחמה", title: "מתיחות אזורית — עלייה בתנודתיות" },
];

const QUICK_ACTIONS = [
  { Icon: Sprout, label: "הזרע אירועים (ברירת מחדל)" },
  { Icon: Refresh, label: "רענן חדשות (RSS)" },
  { Icon: Trash, label: "מחק אירוע" },
  { Icon: Plus, label: "הוסף אירוע חדש" },
];

const signed = (n: number, d = 2) => `${n >= 0 ? "+" : ""}${n.toFixed(d)}%`;

// ─── sub-components ─────────────────────────────────────────────────
function CatChip({ cat }: { cat: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-full" style={{ background: CAT_COLOR[cat] ?? "var(--color-text3)" }} />
      <span className="text-text2">{cat}</span>
    </span>
  );
}

function Timeline({ points, years }: { points: TimelinePoint[]; years: number[] }) {
  const W = 720, H = 360, pad = { t: 20, r: 16, b: 34, l: 44 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const maxAbs = (Math.max(1, ...points.map((p) => Math.abs(p.move)))) * 1.1;
  const sx = (t: number) => pad.l + t * iw;
  const sy = (v: number) => pad.t + ih / 2 - (v / maxAbs) * (ih / 2);
  const y0 = years[0] ?? 0;
  const ySpan = Math.max(1, (years[years.length - 1] ?? y0) - y0);
  const yTicks = [maxAbs, 0, -maxAbs];
  return (
    <SvgChart w={W} h={H} label="ציר זמן — תנועות פקיעה לצד אירועים היסטוריים">
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={pad.l} y1={sy(t)} x2={W - pad.r} y2={sy(t)} stroke="var(--color-grid)" />
          <text x={pad.l - 8} y={sy(t) + 3} textAnchor="end" fontSize="10" fill="var(--color-text3)">
            {t > 0 ? "+" : ""}{t.toFixed(1)}
          </text>
        </g>
      ))}
      {points.filter((p) => p.event).map((p, i) => (
        <line key={`v${i}`} x1={sx(p.t)} y1={pad.t} x2={sx(p.t)} y2={pad.t + ih}
          stroke="var(--color-neg)" strokeWidth="1" strokeDasharray="2 3" opacity="0.4" />
      ))}
      <line x1={pad.l} y1={sy(0)} x2={W - pad.r} y2={sy(0)} stroke="var(--color-text3)" strokeDasharray="4 4" />
      {points.map((p, i) => (
        <circle key={i} cx={sx(p.t)} cy={sy(p.move)} r={p.event ? 4.5 : 2.6}
          fill={p.event ? "var(--color-neg)" : "var(--color-text3)"} opacity={p.event ? 0.9 : 0.55} />
      ))}
      {years.map((y) => (
        <text key={y} x={sx((y - y0) / ySpan)} y={H - pad.b + 16} textAnchor="middle" fontSize="10" fill="var(--color-text3)">{y}</text>
      ))}
      <circle cx={pad.l + 6} cy={9} r="3.5" fill="var(--color-text3)" opacity="0.55" />
      <text x={pad.l + 15} y={12} fontSize="11" fill="var(--color-text2)">רגיל</text>
      <circle cx={pad.l + 62} cy={9} r="4.5" fill="var(--color-neg)" />
      <text x={pad.l + 72} y={12} fontSize="11" fill="var(--color-text2)">עם אירוע</text>
    </SvgChart>
  );
}

function CategoryBars({ data, baseline }: { data: { cat: string; avg: number }[]; baseline: number }) {
  const W = 720, H = 340, pad = { t: 24, r: 16, b: 46, l: 44 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const yMax = (Math.max(baseline, 0.1, ...data.map((d) => d.avg))) * 1.25;
  const bw = iw / Math.max(1, data.length);
  const sy = (v: number) => pad.t + ih - (v / yMax) * ih;
  const yTicks = [0, +(yMax / 2).toFixed(1), +yMax.toFixed(1)];
  return (
    <SvgChart w={W} h={H} label="תנועה ממוצעת לפי קטגוריית אירוע מול בסיס">
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={pad.l} y1={sy(t)} x2={W - pad.r} y2={sy(t)} stroke="var(--color-grid)" />
          <text x={pad.l - 8} y={sy(t) + 3} textAnchor="end" fontSize="10" fill="var(--color-text3)">{t}%</text>
        </g>
      ))}
      {data.map((d, i) => {
        const x = pad.l + i * bw;
        const h = (d.avg / yMax) * ih;
        const cx = x + bw / 2;
        return (
          <g key={d.cat}>
            <rect x={x + 8} y={pad.t + ih - h} width={bw - 16} height={h} rx="2"
              fill={CAT_COLOR[d.cat] ?? "var(--color-text3)"} opacity="0.85" />
            <text x={cx} y={pad.t + ih - h - 5} textAnchor="middle" fontSize="10" fill="var(--color-text2)">
              {d.avg.toFixed(2)}%
            </text>
            <text x={cx} y={H - pad.b + 16} textAnchor="middle" fontSize="11" fill="var(--color-text3)">{d.cat}</text>
          </g>
        );
      })}
      <line x1={pad.l} y1={sy(baseline)} x2={W - pad.r} y2={sy(baseline)} stroke="var(--color-text3)" strokeWidth="1.5" strokeDasharray="5 4" />
      <text x={W - pad.r} y={sy(baseline) - 5} textAnchor="end" fontSize="10" fill="var(--color-text2)">
        בסיס (ללא אירוע): {baseline.toFixed(2)}%
      </text>
    </SvgChart>
  );
}

// ─── view ───────────────────────────────────────────────────────────
export function EventsView({
  events,
  impact,
  timeline,
  years,
  cats,
  baseline,
  extremes,
}: {
  events: EventRow[];
  impact: Impact | null;
  timeline: TimelinePoint[];
  years: number[];
  cats: CatRow[];
  baseline: number;
  extremes: { rows: ExtremeRow[]; explainedPct: number; total: number };
}) {
  const [riskWindow, setRiskWindow] = useState(7);
  const [extremeThresh, setExtremeThresh] = useState(2.5);

  // הסף (2.5%) נשלף מהשרת; המחוון מסנן את השורות שכבר נטענו.
  const shownExtremes = extremes.rows.filter((r) => Math.abs(r.move) >= extremeThresh);
  const explainedShown = shownExtremes.filter((r) => r.ev).length;
  const explainedPct = shownExtremes.length ? (100 * explainedShown) / shownExtremes.length : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">אירועים והקשר</h1>
        <p className="mt-1 text-sm text-text2">
          כיצד אירועים היסטוריים (מלחמות, ריבית, משברים) משפיעים על תנודתיות פקיעות המדד.
        </p>
      </div>

      {/* Section 1: management */}
      <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
        <Panel title="ניהול אירועים">
          <div className="overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="text-xs text-text3">
                  <th className="pb-2 font-medium">#</th>
                  <th className="pb-2 font-medium">תאריך</th>
                  <th className="pb-2 font-medium">קטגוריה</th>
                  <th className="pb-2 font-medium">שם</th>
                  <th className="pb-2 font-medium">תיאור</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} className="border-t border-border">
                    <td className="py-2 tabular-nums text-text3">{e.id}</td>
                    <td className="py-2 tabular-nums text-text2">{e.date}</td>
                    <td className="py-2"><CatChip cat={e.cat} /></td>
                    <td className="py-2 font-medium text-text1">{e.name}</td>
                    <td className="py-2 text-text3">{e.desc}</td>
                  </tr>
                ))}
                {events.length === 0 && (
                  <tr className="border-t border-border">
                    <td colSpan={5} className="py-4 text-center text-text3">אין אירועים להצגה</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="פעולות מהירות">
          <div className="space-y-2">
            {QUICK_ACTIONS.map(({ Icon, label }) => (
              <button key={label}
                className="flex w-full items-center gap-2 rounded-lg border border-border bg-surface2 px-3 py-2 text-right text-sm text-text2 transition hover:text-text1">
                <Icon className="shrink-0 text-text3" /> {label}
              </button>
            ))}
            <p className="pt-1 text-xs text-text3">
              פעולות כתיבה ל-DB (הזרעה / הוספה / מחיקה / חדשות) ייחוברו ל-backend בהמשך.
            </p>
          </div>
        </Panel>
      </div>

      {/* Section 2: impact KPIs */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">השפעה על תנודתיות</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Kpi label="פקיעות עם אירוע" value={impact ? String(impact.withEvent) : "—"} />
          <Kpi label="פקיעות ללא אירוע" value={impact ? String(impact.withoutEvent) : "—"} />
          <Kpi
            label="תנועה ממוצעת — עם אירוע"
            value={impact ? `${impact.avgWith.toFixed(2)}%` : "—"}
            sub={impact ? `${signed(impact.avgWith - impact.avgWithout)} מול רגיל` : undefined}
            subTone="text-warn"
          />
          <Kpi
            label="פקיעות >2% — עם אירוע"
            value={impact ? `${impact.gt2With.toFixed(1)}%` : "—"}
            tone="text-warn"
            sub={impact ? `${signed(impact.gt2With - impact.gt2Without, 1)} מול רגיל` : undefined}
            subTone="text-warn"
          />
          <Kpi label="פקיעות <1% — עם אירוע" value={impact ? `${impact.lt1With.toFixed(1)}%` : "—"} />
        </div>
      </div>

      {/* Section 3: timeline */}
      <Panel title="ציר זמן — פקיעות ואירועים" sub="כל נקודה = פקיעה · קו אנכי = אירוע">
        <Timeline points={timeline} years={years} />
      </Panel>

      {/* Section 4: by category */}
      <div className="space-y-3">
        <h2 className="text-lg font-bold tracking-tight">פירוט לפי קטגוריית אירוע</h2>
        <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
          <Panel>
            <CategoryBars data={cats} baseline={baseline} />
          </Panel>
          <Panel>
            <div className="overflow-x-auto">
              <table className="w-full text-right text-sm">
                <thead>
                  <tr className="text-xs text-text3">
                    <th className="pb-2 font-medium">קטגוריה</th>
                    <th className="pb-2 font-medium">פקיעות</th>
                    <th className="pb-2 font-medium">תנועה ממוצעת</th>
                    <th className="pb-2 font-medium">מקס |move|</th>
                    <th className="pb-2 font-medium">{">"}2%</th>
                  </tr>
                </thead>
                <tbody>
                  {cats.map((c) => (
                    <tr key={c.cat} className="border-t border-border">
                      <td className="py-2"><CatChip cat={c.cat} /></td>
                      <td className="py-2 tabular-nums text-text2">{c.count}</td>
                      <td className="py-2 tabular-nums text-text1">{c.avg.toFixed(2)}%</td>
                      <td className="py-2 tabular-nums text-text2">{c.max.toFixed(2)}%</td>
                      <td className="py-2 tabular-nums text-text2">{c.gt2.toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      </div>

      {/* Section 5: risk score (עדיין דמו — לוגיקת ניקוד תיבנה בהמשך) */}
      <div className="space-y-3">
        <h2 className="text-lg font-bold tracking-tight">ציון סיכון לפקיעה הקרובה</h2>
        <div className="grid gap-5 lg:grid-cols-[1fr_2fr]">
          <Panel>
            <div className="space-y-4">
              <div>
                <div className="mb-1 text-xs text-text3">תאריך פקיעה קרובה</div>
                <div className="text-sm font-semibold text-text1">03/07/2026</div>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between text-xs text-text3">
                  <span>חלון חיפוש (ימים)</span>
                  <span className="font-semibold tabular-nums text-text1">{riskWindow}</span>
                </div>
                <input type="range" min={3} max={14} step={1} value={riskWindow}
                  onChange={(e) => setRiskWindow(parseInt(e.target.value))}
                  className="w-full accent-[var(--color-accent)]" />
              </div>
            </div>
          </Panel>

          <Panel>
            <div className="rounded-xl border border-warn/30 bg-warn/5 p-5">
              <div className="text-xs text-text3">ציון סיכון תנודתיות — פקיעה 03/07/2026</div>
              <div className="mt-1 flex items-center gap-2 text-3xl font-extrabold text-warn">
                4.2 / 10
                <span className="inline-flex items-center gap-1.5 text-2xl">
                  <Dot /> בינוני
                </span>
              </div>
              <div className="mt-2 text-sm text-text2">
                <b className="text-text1">אירועים בחלון:</b> החלטת ריבית בנק ישראל · פקיעת חוזים בארה״ב
              </div>
              <div className="mt-1 text-sm text-text2">
                תנועה ממוצעת עם אירוע:{" "}
                <b className="text-text1">{impact ? `${impact.avgWith.toFixed(2)}%` : "—"}</b> לעומת ללא אירוע:{" "}
                <b className="text-text1">{baseline.toFixed(2)}%</b>
              </div>
            </div>
            <div className="mt-3 rounded-xl border border-accent/20 bg-accent/5 p-4 text-sm text-text2">
              <b className="text-text1">סיכון בינוני</b> — בדוק את אופי האירוע. אירועי ריבית לרוב
              מניעים שוק מכוון; אירועי מלחמה מוסיפים אי-ודאות. שמור על גמישות בין Iron Condor
              ל-Straddle.
            </div>
          </Panel>
        </div>
      </div>

      {/* Section 6: extreme expiries */}
      <div className="space-y-3">
        <h2 className="text-lg font-bold tracking-tight">פקיעות קיצוניות — מוסברות על-ידי אירועים</h2>
        <Panel>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <label className="text-xs text-text3">סף קיצוניות |move| (%)</label>
              <input type="range" min={2.5} max={5} step={0.5} value={extremeThresh}
                onChange={(e) => setExtremeThresh(parseFloat(e.target.value))}
                className="accent-[var(--color-accent)]" />
              <span className="text-xs font-semibold tabular-nums text-text1">{extremeThresh.toFixed(1)}%</span>
            </div>
            <div className="text-xs text-text2">
              נמצאו <b className="text-text1">{shownExtremes.length}</b> פקיעות מעל {extremeThresh.toFixed(1)}% ·{" "}
              <b className="text-text1">{explainedPct.toFixed(1)}%</b> מוסברות על-ידי אירוע בחלון 7 ימים
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="text-xs text-text3">
                  <th className="pb-2 font-medium">תאריך</th>
                  <th className="pb-2 font-medium">סוג</th>
                  <th className="pb-2 font-medium">תנועה (%)</th>
                  <th className="pb-2 font-medium">אירוע?</th>
                  <th className="pb-2 font-medium">אירועים</th>
                </tr>
              </thead>
              <tbody>
                {shownExtremes.map((r, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-2 tabular-nums text-text2">{r.date}</td>
                    <td className="py-2 text-text2">{r.type}</td>
                    <td className={`py-2 tabular-nums font-semibold ${r.move >= 0 ? "text-pos" : "text-neg"}`} dir="ltr">
                      {r.move > 0 ? "+" : ""}{r.move.toFixed(2)}%
                    </td>
                    <td className="py-2">{r.ev ? <span className="text-pos">✓</span> : <span className="text-text3">—</span>}</td>
                    <td className="py-2 text-text3">{r.ev || "—"}</td>
                  </tr>
                ))}
                {shownExtremes.length === 0 && (
                  <tr className="border-t border-border">
                    <td colSpan={5} className="py-4 text-center text-text3">אין פקיעות מעל הסף</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* Section 7: telegram (עדיין mock) */}
      <div className="space-y-3">
        <h2 className="text-lg font-bold tracking-tight">חדשות מטלגרם אחרונות</h2>
        <Panel>
          <div className="overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="text-xs text-text3">
                  <th className="pb-2 font-medium">תאריך</th>
                  <th className="pb-2 font-medium">קטגוריה</th>
                  <th className="pb-2 font-medium">כותרת</th>
                </tr>
              </thead>
              <tbody>
                {TELEGRAM.map((t, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-2 tabular-nums text-text2">{t.date}</td>
                    <td className="py-2"><CatChip cat={t.cat} /></td>
                    <td className="py-2 text-text1">{t.title}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <Disclaimer>
        הניתוח מבוסס על קישור סטטיסטי בין פקיעות לאירועים — לא קשר סיבתי מוכח. ציון
        הסיכון הוא אינדיקטור תיאורטי בלבד, לא המלצת מסחר. מסחר באופציות כרוך בסיכון של אובדן מלא.
      </Disclaimer>
    </div>
  );
}
