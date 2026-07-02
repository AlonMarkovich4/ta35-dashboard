"use client";

import { useState, useMemo } from "react";
import { Panel } from "@/components/ui/Panel";
import { AccordionItem } from "@/components/ui/Accordion";
import { FilterRow } from "@/components/ui/FilterRow";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Empty } from "@/components/ui/Empty";
import { runBacktest, bestPerStrategy } from "@/lib/strategies";
import type { MoveRow } from "@/lib/data";

// תיאורי אסטרטגיה (טקסט UI, לפי id)
const DESC: Record<number, string> = {
  1: "מנצחת כשהמדד עולה (move_pct > 0). רוחב הספרד קובע תקרת רווח.",
  2: "מנצחת כשהמדד נשאר בתוך ±טווח% מהבסיס. מוכר טווח רחב.",
  3: "מנצחת כשהפקיעה ממש ליד ATM — תנועה קטנה מרוחב הכנף.",
  4: "מבנה מראה של Call Butterfly. אותו תנאי ניצחון — תנועה קטנה.",
  5: "מנצחת בתנועה חזקה לכל כיוון (מעל סף שבירת פרמיה).",
  6: "קנייה OTM — דורשת תנועה גדולה יותר מ-Straddle לשביר.",
};

type UIVariant = { param: string; wr: number; wins: number; losses: number; avgIntensity: number };
type UIStrat = {
  id: number;
  name: string;
  desc: string;
  variants: UIVariant[];
  best: UIVariant;
  sameWinRate: boolean;
};

// ─── Sub-components ─────────────────────────────────────────────────
function WinBar({ wr, height = "h-5" }: { wr: number; height?: string }) {
  const pct = Math.round(wr * 100);
  const good = wr >= 0.5;
  return (
    <div className={`relative ${height} overflow-hidden rounded bg-surface2`}>
      <div className={`h-full ${good ? "bg-pos/80" : "bg-neg/80"}`} style={{ width: `${pct}%` }} />
      <div className="absolute inset-y-0 left-1/2 w-px bg-border2" />
      <span className="absolute inset-y-0 right-2 flex items-center text-[11px] font-semibold tabular-nums text-text1">
        {pct}%
      </span>
    </div>
  );
}

function SummaryTable({ strats }: { strats: UIStrat[] }) {
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
          {strats.map((s) => {
            const b = s.best;
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
                      <div className={`h-full ${good ? "bg-pos" : "bg-neg"}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className={`text-xs font-semibold tabular-nums ${good ? "text-pos" : "text-neg"}`}>
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

function SummaryChart({ strats }: { strats: UIStrat[] }) {
  const rows = [...strats]
    .map((s) => ({ name: s.name, wr: s.best.wr }))
    .sort((a, b) => a.wr - b.wr);
  return (
    <div className="space-y-2.5">
      {rows.map((r) => (
        <div key={r.name} className="grid grid-cols-[130px_1fr] items-center gap-3">
          <div className="truncate text-xs text-text2">{r.name}</div>
          <WinBar wr={r.wr} />
        </div>
      ))}
    </div>
  );
}

function VariantTable({ variants }: { variants: UIVariant[] }) {
  return (
    <table className="w-full text-right text-sm">
      <thead>
        <tr className="text-xs text-text3">
          <th className="pb-2 font-medium">פרמטר</th>
          <th className="pb-2 font-medium">Win Rate</th>
          <th className="pb-2 font-medium">ניצחונות</th>
          <th className="pb-2 font-medium">הפסדות</th>
          <th className="pb-2 font-medium">עוצמה</th>
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
                <span className={`text-xs font-semibold tabular-nums ${good ? "text-pos" : "text-neg"}`}>
                  {pct}%
                </span>
              </td>
              <td className="py-2 tabular-nums text-text2">{v.wins}</td>
              <td className="py-2 tabular-nums text-text2">{v.losses}</td>
              <td className="py-2 tabular-nums text-text3">{v.avgIntensity.toFixed(2)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function VariantChart({ variants }: { variants: UIVariant[] }) {
  return (
    <div className="space-y-2">
      {variants.map((v) => (
        <div key={v.param} className="grid grid-cols-[110px_1fr] items-center gap-2">
          <div className="truncate text-[11px] text-text3">{v.param}</div>
          <WinBar wr={v.wr} height="h-4" />
        </div>
      ))}
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

export function StrategiesView({ moves }: { moves: MoveRow[] }) {
  const [type, setType] = useState<TypeV>("all");
  const typeLabel = TYPE_OPTS.find((o) => o.v === type)!.l;

  const { strats, total, yearRange } = useMemo(() => {
    // filter → backtest → best
    const filtered = type === "all" ? moves : moves.filter((m) => m.type === type);
    const results = runBacktest(filtered.map((m) => m.move));
    const bestById = new Map(bestPerStrategy(results).map((b) => [b.strategyId, b]));

    // group variants by strategy (preserving grid order); best from bestPerStrategy
    const byId = new Map<number, typeof results>();
    for (const r of results) {
      const arr = byId.get(r.strategyId) ?? [];
      arr.push(r);
      byId.set(r.strategyId, arr);
    }
    const strats: UIStrat[] = [...byId.values()].map((variants) => {
      const b = bestById.get(variants[0].strategyId)!;
      const sameWinRate = variants.every((v) => v.winRate === variants[0].winRate);
      return {
        id: variants[0].strategyId,
        name: variants[0].strategyName,
        desc: DESC[variants[0].strategyId] ?? "",
        variants: variants.map((v) => ({
          param: v.paramsRepr, wr: v.winRate, wins: v.wins, losses: v.losses, avgIntensity: v.avgIntensity,
        })),
        best: { param: b.paramsRepr, wr: b.winRate, wins: b.wins, losses: b.losses, avgIntensity: b.avgIntensity },
        sameWinRate,
      };
    });

    const years = moves.map((m) => m.year);
    const yearRange = years.length ? `${Math.min(...years)}–${Math.max(...years)}` : "—";
    return { strats, total: filtered.length, yearRange };
  }, [type, moves]);

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
          <div className="text-xs text-text3">טווח שנים: {yearRange}</div>
        </div>
        <div className="mt-3 text-xs text-text2">
          מבוסס על <span className="font-semibold tabular-nums text-text1">{total}</span>{" "}
          פקיעות · סוג: <span className="font-semibold text-text1">{typeLabel}</span>{" "}
          · שנים: <span className="tabular-nums text-text1">{yearRange}</span>
        </div>
      </Panel>

      {total === 0 ? (
        <Empty title="אין פקיעות לסוג שנבחר" />
      ) : (
        <>
          <Panel
            title="סיכום — הפרמטר המיטבי לכל אסטרטגיה"
            sub="הוריאנט עם ה-Win Rate הגבוה ביותר בכל אסטרטגיה"
          >
            <div className="grid gap-8 lg:grid-cols-[3fr_2fr]">
              <SummaryTable strats={strats} />
              <div>
                <div className="mb-3 text-xs text-text3">
                  Win Rate לפי אסטרטגיה (קו = סף 50%)
                </div>
                <SummaryChart strats={strats} />
              </div>
            </div>
          </Panel>

          <div className="space-y-3">
            <h2 className="text-lg font-bold tracking-tight">
              פירוט וריאנטים לפי אסטרטגיה
            </h2>
            {strats.map((s) => {
              const pct = Math.round(s.best.wr * 100);
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
                        <span className="font-bold tabular-nums text-text1">{pct}%</span>
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
                          <span className="font-bold text-accent tabular-nums">{pct}%</span>
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
        </>
      )}

      <Disclaimer>
        Win Rate היסטורי אינו מבטיח תוצאות עתידיות. הניתוח מבוסס על כיוון התנועה
        בלבד — אינו מחשב פרמיות, עלויות עסקה או סיכון אמיתי. כלי מחקר בלבד.
      </Disclaimer>
    </div>
  );
}
