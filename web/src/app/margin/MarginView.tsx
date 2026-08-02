import { Panel } from "@/components/ui/Panel";
import { Kpi } from "@/components/ui/Kpi";
import { AccordionItem } from "@/components/ui/Accordion";
import { Empty } from "@/components/ui/Empty";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Spark, Target } from "@/components/icons";
import { pct, pctFrac } from "@/lib/format";
import { LiveRecommendations } from "./LiveRecommendations";
import type { MarginData } from "@/lib/data";

// פער חתום (+1.00% / -1.00%); מקור התנועה בעברית.
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

      {/* ── חלק 1: ההמלצות החיות (טבלה נלחצת + גרף Payoff) ── */}
      <LiveRecommendations live={live} />

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
                sub={
                  summary.holdRate1session == null
                    ? `${summary.nHeld}/${summary.nValidated} החזיקו`
                    : `${summary.nHeld}/${summary.nValidated} החזיקו · לפי הגדרת הבקטסט: ${pctFrac(summary.holdRate1session, 0)}`
                }
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
            <b className="text-text1">4 הרגליים והכנף:</b> מכירת short put/call (הרגל המכורה) וקניית
            long put/call כהגנה, במרחק הכנף (הרשמית 0.75%) מעבר ל-short. הגרף מציג את הטרפז: רווח
            הפרמיה בין ה-shorts, ירידה ליניארית עד ה-longs, והפסד-מקס מעבר להם.
          </li>
          <li>
            <b className="text-text1">החזיק / נשבר:</b> מחיר הסילוק האמיתי נפל בין ה-short
            strikes של ההמלצה — כלומר האם הפוזיציה שנפתחה באמת שרדה, על פני כל תקופת
            החשיפה (5–7 מושבים).{" "}
            <b className="text-text1">שים לב:</b> המספר בסוגריים (&quot;לפי הגדרת הבקטסט&quot;)
            מודד תנועת <b className="text-text1">מושב אחד</b> בלבד, וקיים רק כדי להשוות
            ל-<code>margin_backtest</code>. הוא גבוה בהרבה, והוא <b className="text-text1">אינו</b>{" "}
            שיעור ההחזקה בפועל — עד 02/08/2026 הוא זה שהוצג כאן בטעות.
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
