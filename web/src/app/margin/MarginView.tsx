import { Fragment } from "react";
import { Panel } from "@/components/ui/Panel";
import { Kpi } from "@/components/ui/Kpi";
import { AccordionItem } from "@/components/ui/Accordion";
import { Empty } from "@/components/ui/Empty";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Spark, Target } from "@/components/icons";
import { pct, pctFrac, ils, en } from "@/lib/format";
import type { MarginData } from "@/lib/data";

// מרווח באחוזים (1.75 → "1.75%"); פער חתום (+1.00% / -1.00%); מקור התנועה בעברית.
const gapFmt = (v: number | null) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);
const MOVE_SOURCE: Record<string, string> = {
  expiry_history: "היסטוריה",
  settlement: "סטלמנט",
};

// מנגנון המרווח האופטימלי (Short Iron Condor): ההמלצות החיות + ולידציה קדימה.
export function MarginView({ data }: { data: MarginData }) {
  const { live, validation } = data;
  const { rows, summary } = validation;

  return (
    <div className="space-y-6">
      <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
        <Spark className="text-accent" /> מרווח אופטימלי
      </h1>

      <div className="rounded-xl border border-border bg-surface2/40 px-4 py-3 text-sm text-text2">
        <b className="text-text1">Short Iron Condor:</b> לכל פקיעה המנוע בוחר את המרווח הצר ביותר
        שהביטחון המשוקלל שלו עומד בסף (floor 97%) — האיזון בין פרמיה לעקביות. כלי מחקר בלבד, לא ייעוץ.
      </div>

      {/* ── חלק 1: ההמלצות החיות ── */}
      <div className="space-y-4">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight">
            <Target className="text-accent" /> ההמלצות החיות
          </h2>
          <p className="mt-0.5 text-xs text-text3">
            ההמלצה האחרונה לכל פקיעה קרובה (גרסה margin-v1.1).
          </p>
        </div>

        {live.length === 0 ? (
          <Empty title="אין המלצות חיות" hint="ההמלצות מתועדות אוטומטית לפקיעות הקרובות." />
        ) : (
          <Panel>
            <div className="overflow-x-auto">
              <table className="w-full text-right text-sm">
                <thead>
                  <tr className="text-xs text-text3">
                    <th className="pb-2 font-medium">פקיעה</th>
                    <th className="pb-2 font-medium">מרווח מומלץ</th>
                    <th className="pb-2 font-medium">hold משוקלל</th>
                    <th className="pb-2 font-medium">hold מותנה</th>
                    <th className="pb-2 font-medium">hold גלובלי</th>
                    <th className="pb-2 font-medium">פרמיה צפויה</th>
                    <th className="pb-2 font-medium">Short strikes</th>
                  </tr>
                </thead>
                <tbody>
                  {live.map((r, i) => (
                    <Fragment key={i}>
                      <tr className="border-t border-border">
                        <td className="py-2.5 tabular-nums text-text2" dir="ltr">{r.expiry}</td>
                        <td className="py-2.5">
                          <span className="text-base font-bold tabular-nums text-accent">
                            {pct(r.marginPct, 2)}
                          </span>
                          {r.belowFloor && (
                            <span className="mr-2 rounded-md bg-warn/15 px-1.5 py-0.5 text-[10px] font-semibold text-warn">
                              מתחת לסף
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 tabular-nums font-semibold text-text1">
                          {pctFrac(r.holdBlended, 1)}
                        </td>
                        <td className="py-2.5 tabular-nums text-text2">
                          {pctFrac(r.holdConditional, 1)}
                          <span className="text-[11px] text-text3"> (n={r.nConditional ?? "—"})</span>
                        </td>
                        <td className="py-2.5 tabular-nums text-text2">{pctFrac(r.holdGlobal, 1)}</td>
                        <td className="py-2.5 tabular-nums text-text1" dir="ltr">{ils(r.premiumIls)}</td>
                        <td className="py-2.5 tabular-nums text-text2" dir="ltr">
                          {en(r.shortPutStrike)}P / {en(r.shortCallStrike)}C
                        </td>
                      </tr>
                      {r.reason && (
                        <tr>
                          <td colSpan={7} className="pb-3 pt-0 text-xs text-text3">
                            ➜ {r.reason}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 text-xs text-text3">
              מוצגות {live.length} פקיעות קרובות · עודכן לאחרונה {live[0]?.recommendedAt}
            </div>
          </Panel>
        )}
      </div>

      {/* ── חלק 2: ולידציית המרווח ── */}
      <div className="space-y-4">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight">
            <Target className="text-accent" /> ולידציית המרווח
          </h2>
          <p className="mt-0.5 text-xs text-text3">
            עקביות בפועל: המרווח שהומלץ מול התנועה שקרתה — לכל פקיעה מומלצת שנסגרה.
          </p>
        </div>

        {summary.nValidated === 0 ? (
          <Empty
            title="אין עדיין פקיעות לוַלִידציה"
            hint="הוולידציה תתמלא עם סגירת פקיעות מומלצות (כשיש להן גם המלצה וגם settlement)."
          />
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <Kpi label="פקיעות שנוולדו" value={String(summary.nValidated)} />
              <Kpi
                label="hold בפועל"
                value={pctFrac(summary.holdRate, 0)}
                tone="text-accent"
                sub={`${summary.nHeld}/${summary.nValidated} החזיקו`}
              />
              <Kpi
                label="פער ממוצע מהאופטימום"
                value={gapFmt(summary.avgMarginGap)}
                sub="מרווח שבוזבז (+) / חסר (−)"
              />
            </div>

            <Panel title="פירוט לפי פקיעה" sub="המרווח המומלץ מול המציאות">
              <div className="overflow-x-auto">
                <table className="w-full text-right text-sm">
                  <thead>
                    <tr className="text-xs text-text3">
                      <th className="pb-2 font-medium">פקיעה</th>
                      <th className="pb-2 font-medium">מרווח שהומלץ</th>
                      <th className="pb-2 font-medium">|תנועה|</th>
                      <th className="pb-2 font-medium">תוצאה</th>
                      <th className="pb-2 font-medium">אופטימום בדיעבד</th>
                      <th className="pb-2 font-medium">פער</th>
                      <th className="pb-2 font-medium">מקור</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className="border-t border-border">
                        <td className="py-2.5 tabular-nums text-text2" dir="ltr">{r.expiry}</td>
                        <td className="py-2.5 tabular-nums font-semibold text-text1">
                          {pct(r.recommendedMargin, 2)}
                        </td>
                        <td className="py-2.5 tabular-nums text-text2" dir="ltr">
                          {pct(r.actualAbsMovePct, 2)}
                        </td>
                        <td className="py-2.5">
                          {r.held ? (
                            <span className="font-semibold text-pos">✓ החזיק</span>
                          ) : (
                            <span className="font-semibold text-neg">✗ נשבר</span>
                          )}
                        </td>
                        <td className="py-2.5 tabular-nums text-text2">
                          {r.optimalHindsight == null ? "—" : pct(r.optimalHindsight, 2)}
                        </td>
                        <td
                          className={`py-2.5 tabular-nums ${r.gap == null ? "text-text3" : r.gap > 0 ? "text-text2" : "text-neg"}`}
                          dir="ltr"
                        >
                          {gapFmt(r.gap)}
                        </td>
                        <td className="py-2.5 text-text3">{MOVE_SOURCE[r.moveSource] ?? r.moveSource}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-2 text-xs text-text3">
                נוולדו {summary.nValidated} פקיעות — לכל אחת המלצה מתועדת וגם settlement.
              </div>
            </Panel>
          </>
        )}
      </div>

      {/* שקיפות */}
      <AccordionItem header={<span className="font-semibold">איך זה נמדד (שקיפות)</span>}>
        <ul className="space-y-2.5 text-sm text-text2">
          <li>
            <b className="text-text1">מרווח מומלץ:</b> הצר ביותר שהביטחון המשוקלל שלו ≥ סף 97%.
            מרווח צר משלם פרמיה גבוהה יותר אך נשבר לעתים קרובות יותר; רחב עקבי אך זול.
          </li>
          <li>
            <b className="text-text1">hold (משוקלל / מותנה / גלובלי):</b> ההסתברות ההיסטורית
            שהתנועה תישאר בתוך המרווח. מותנה = פקיעות דומות (סוג + תנועה קודמת); גלובלי = כל
            ההיסטוריה מאותו סוג; משוקלל = השילוב (משקל המותנה קטן כשהמדגם קטן).
          </li>
          <li>
            <b className="text-text1">החזיק / נשבר:</b> |תנועה בפועל| ≤ המרווח המומלץ — אותה הגדרה
            בדיוק כמו בסימולציה ההיסטורית, כך ש-hold בפועל בר-השוואה ל-hold של הבקטסט.
          </li>
          <li>
            <b className="text-text1">אופטימום בדיעבד ופער:</b> המרווח הצר ביותר שהיה מחזיק את
            התנועה שקרתה. הפער = מומלץ − אופטימום: חיובי = מרווח שבוזבז (פרמיה שהוותרנו); שלילי =
            המרווח לא הספיק (נשבר).
          </li>
          <li>
            <b className="text-text1">מקור התנועה:</b> move_pct הקנוני מ-expiry_history כשקיים,
            אחרת חישוב מ-settlement (מדד הנעילה מול מדד הבסיס של ההמלצה). קריאה-בלבד, אפס כתיבה.
          </li>
        </ul>
      </AccordionItem>

      <Disclaimer>
        כלי מחקר בלבד — לא ייעוץ השקעות ולא המלצת מסחר. המנוע מציג ומתעד את המרווח, לא מבצע עסקאות.
      </Disclaimer>
    </div>
  );
}
