"use client";

import { useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { AccordionItem } from "@/components/ui/Accordion";
import { FilterRow } from "@/components/ui/FilterRow";
import { Disclaimer } from "@/components/ui/Disclaimer";

// ─── Mock data (נאמן-צורה; יוחלף בנתוני Supabase בשלב 4) ─────────────
const TOTAL = 965;
const mk = (wr: number) => ({
  wins: Math.round(wr * TOTAL),
  losses: TOTAL - Math.round(wr * TOTAL),
});

type Variant = { param: string; wr: number; wins: number; losses: number };
type Strat = {
  id: number;
  name: string;
  desc: string;
  variants: Variant[];
  sameWinRate?: boolean;
};

const STRATS: Strat[] = [
  {
    id: 1,
    name: "Bull Call Spread",
    desc: "מנצחת כשהמדד עולה (move_pct > 0). רוחב הספרד קובע תקרת רווח.",
    sameWinRate: true,
    variants: [
      { param: "width_pts=10", wr: 0.52, ...mk(0.52) },
      { param: "width_pts=20", wr: 0.52, ...mk(0.52) },
      { param: "width_pts=30", wr: 0.52, ...mk(0.52) },
      { param: "width_pts=50", wr: 0.52, ...mk(0.52) },
    ],
  },
  {
    id: 2,
    name: "Short Iron Condor",
    desc: "מנצחת כשהמדד נשאר בתוך ±טווח% מהבסיס. מוכר טווח רחב.",
    variants: [
      { param: "width_pct=1.0", wr: 0.41, ...mk(0.41) },
      { param: "width_pct=1.5", wr: 0.52, ...mk(0.52) },
      { param: "width_pct=2.0", wr: 0.61, ...mk(0.61) },
      { param: "width_pct=2.5", wr: 0.68, ...mk(0.68) },
      { param: "width_pct=3.0", wr: 0.73, ...mk(0.73) },
    ],
  },
  {
    id: 3,
    name: "Long Call Butterfly",
    desc: "מנצחת כשהפקיעה ממש ליד ATM — תנועה קטנה מרוחב הכנף.",
    variants: [
      { param: "wing_pct=0.5", wr: 0.22, ...mk(0.22) },
      { param: "wing_pct=1.0", wr: 0.38, ...mk(0.38) },
      { param: "wing_pct=1.5", wr: 0.49, ...mk(0.49) },
      { param: "wing_pct=2.0", wr: 0.58, ...mk(0.58) },
    ],
  },
  {
    id: 4,
    name: "Long Put Butterfly",
    desc: "מבנה מראה של Call Butterfly. אותו תנאי ניצחון — תנועה קטנה.",
    variants: [
      { param: "wing_pct=0.5", wr: 0.2, ...mk(0.2) },
      { param: "wing_pct=1.0", wr: 0.36, ...mk(0.36) },
      { param: "wing_pct=1.5", wr: 0.47, ...mk(0.47) },
      { param: "wing_pct=2.0", wr: 0.56, ...mk(0.56) },
    ],
  },
  {
    id: 5,
    name: "Long Straddle",
    desc: "מנצחת בתנועה חזקה לכל כיוון (מעל סף שבירת פרמיה).",
    variants: [
      { param: "min_move=0.5", wr: 0.62, ...mk(0.62) },
      { param: "min_move=1.0", wr: 0.47, ...mk(0.47) },
      { param: "min_move=1.5", wr: 0.36, ...mk(0.36) },
      { param: "min_move=2.0", wr: 0.27, ...mk(0.27) },
    ],
  },
  {
    id: 6,
    name: "Long Strangle",
    desc: "קנייה OTM — דורשת תנועה גדולה יותר מ-Straddle לשביר.",
    variants: [
      { param: "min_move=1.0", wr: 0.47, ...mk(0.47) },
      { param: "min_move=1.5", wr: 0.36, ...mk(0.36) },
      { param: "min_move=2.0", wr: 0.27, ...mk(0.27) },
      { param: "min_move=2.5", wr: 0.2, ...mk(0.2) },
    ],
  },
];

const bestVariant = (s: Strat) =>
  s.variants.reduce((a, b) => (b.wr > a.wr ? b : a));

// ─── Sub-components ─────────────────────────────────────────────────
function WinBar({ wr, height = "h-5" }: { wr: number; height?: string }) {
  const pct = Math.round(wr * 100);
  const good = wr >= 0.5;
  return (
    <div className={`relative ${height} overflow-hidden rounded bg-surface2`}>
      <div
        className={`h-full ${good ? "bg-pos/80" : "bg-neg/80"}`}
        style={{ width: `${pct}%` }}
      />
      <div className="absolute inset-y-0 left-1/2 w-px bg-border2" />
      <span className="absolute inset-y-0 right-2 flex items-center text-[11px] font-semibold tabular-nums text-text1">
        {pct}%
      </span>
    </div>
  );
}

function SummaryTable() {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-right text-sm">
        <thead>
          <tr className="text-xs text-text3">
            <th className="pb-2 font-medium">#</th>
            <th className="pb-2 font-medium">אסטרטגיה</th>
            <th className="pb-2 font-medium">פרמטר מיטבי</th>
            <th className="pb-2 font-medium">Win Rate</th>
            <th className="pb-2 font-medium">ניצחונות</th>
            <th className="pb-2 font-medium">הפסדות</th>
          </tr>
        </thead>
        <tbody>
          {STRATS.map((s) => {
            const b = bestVariant(s);
            const pct = Math.round(b.wr * 100);
            const good = b.wr >= 0.5;
            return (
              <tr key={s.id} className="border-t border-border">
                <td className="py-2.5 tabular-nums text-text3">{s.id}</td>
                <td className="py-2.5 font-medium">{s.name}</td>
                <td className="py-2.5 tabular-nums text-text2">{b.param}</td>
                <td className="py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface2">
                      <div
                        className={`h-full ${good ? "bg-pos" : "bg-neg"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span
                      className={`text-xs font-semibold tabular-nums ${good ? "text-pos" : "text-neg"}`}
                    >
                      {pct}%
                    </span>
                  </div>
                </td>
                <td className="py-2.5 tabular-nums text-text2">{b.wins}</td>
                <td className="py-2.5 tabular-nums text-text2">{b.losses}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SummaryChart() {
  const rows = [...STRATS]
    .map((s) => ({ name: s.name, wr: bestVariant(s).wr }))
    .sort((a, b) => a.wr - b.wr);
  return (
    <div className="space-y-2.5">
      {rows.map((r) => (
        <div
          key={r.name}
          className="grid grid-cols-[130px_1fr] items-center gap-3"
        >
          <div className="truncate text-xs text-text2">{r.name}</div>
          <WinBar wr={r.wr} />
        </div>
      ))}
    </div>
  );
}

function VariantTable({ variants }: { variants: Variant[] }) {
  return (
    <table className="w-full text-right text-sm">
      <thead>
        <tr className="text-xs text-text3">
          <th className="pb-2 font-medium">פרמטר</th>
          <th className="pb-2 font-medium">Win Rate</th>
          <th className="pb-2 font-medium">ניצחונות</th>
          <th className="pb-2 font-medium">הפסדות</th>
        </tr>
      </thead>
      <tbody>
        {variants.map((v) => {
          const pct = Math.round(v.wr * 100);
          const good = v.wr >= 0.5;
          return (
            <tr key={v.param} className="border-t border-border">
              <td className="py-2 tabular-nums text-text2">{v.param}</td>
              <td className="py-2">
                <span
                  className={`text-xs font-semibold tabular-nums ${good ? "text-pos" : "text-neg"}`}
                >
                  {pct}%
                </span>
              </td>
              <td className="py-2 tabular-nums text-text2">{v.wins}</td>
              <td className="py-2 tabular-nums text-text2">{v.losses}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function VariantChart({ variants }: { variants: Variant[] }) {
  return (
    <div className="space-y-2">
      {variants.map((v) => (
        <div
          key={v.param}
          className="grid grid-cols-[110px_1fr] items-center gap-2"
        >
          <div className="truncate text-[11px] text-text3">{v.param}</div>
          <WinBar wr={v.wr} height="h-4" />
        </div>
      ))}
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

export default function StrategiesPage() {
  const [type, setType] = useState<TypeV>("all");
  const typeLabel = TYPE_OPTS.find((o) => o.v === type)!.l;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">השוואת אסטרטגיות</h1>
        <p className="mt-1 text-sm text-text2">
          Win Rate של 6 אסטרטגיות אופציות על פקיעות היסטוריות — grid search על כל
          פרמטרי האפיון.
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
        <div className="mt-3 text-xs text-text2">
          מבוסס על <span className="font-semibold tabular-nums text-text1">965</span>{" "}
          פקיעות · סוג: <span className="font-semibold text-text1">{typeLabel}</span>{" "}
          · שנים: <span className="tabular-nums text-text1">2010–2026</span>
        </div>
      </Panel>

      <Panel
        title="סיכום — הפרמטר המיטבי לכל אסטרטגיה"
        sub="הוריאנט עם ה-Win Rate הגבוה ביותר בכל אסטרטגיה"
      >
        <div className="grid gap-8 lg:grid-cols-[3fr_2fr]">
          <SummaryTable />
          <div>
            <div className="mb-3 text-xs text-text3">
              Win Rate לפי אסטרטגיה (קו = סף 50%)
            </div>
            <SummaryChart />
          </div>
        </div>
      </Panel>

      <div className="space-y-3">
        <h2 className="text-lg font-bold tracking-tight">
          פירוט וריאנטים לפי אסטרטגיה
        </h2>
        {STRATS.map((s) => {
          const b = bestVariant(s);
          const pct = Math.round(b.wr * 100);
          return (
            <AccordionItem
              key={s.id}
              header={
                <div className="flex items-center justify-between gap-3 pl-2">
                  <span className="font-semibold">
                    #{s.id} — {s.name}
                  </span>
                  <span className="text-sm text-text2">
                    Win Rate מיטבי:{" "}
                    <span className="font-bold tabular-nums text-text1">
                      {pct}%
                    </span>
                  </span>
                </div>
              }
            >
              <p className="mb-4 text-sm text-text2">{s.desc}</p>
              <div className="grid gap-6 md:grid-cols-2">
                <VariantTable variants={s.variants} />
                {s.sameWinRate ? (
                  <div className="flex items-center rounded-xl border border-accent/25 bg-accent/10 p-4 text-sm text-text2">
                    <span>
                      Win Rate זהה לכל הוריאנטים:{" "}
                      <span className="font-bold text-accent tabular-nums">
                        {pct}%
                      </span>
                      . רוחב הספרד משפיע על גובה הרווח, לא על הסתברות הניצחון.
                    </span>
                  </div>
                ) : (
                  <VariantChart variants={s.variants} />
                )}
              </div>
            </AccordionItem>
          );
        })}
      </div>

      <Disclaimer>
        Win Rate היסטורי אינו מבטיח תוצאות עתידיות. הניתוח מבוסס על כיוון התנועה
        בלבד — אינו מחשב פרמיות, עלויות עסקה או סיכון אמיתי. כלי מחקר בלבד.
      </Disclaimer>
    </div>
  );
}
