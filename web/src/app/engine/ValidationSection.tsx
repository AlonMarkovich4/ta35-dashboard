import { Panel } from "@/components/ui/Panel";
import { Kpi } from "@/components/ui/Kpi";
import { AccordionItem } from "@/components/ui/Accordion";
import { Empty } from "@/components/ui/Empty";
import { Target, Dot } from "@/components/icons";
import { money, ils, pctFrac, pnlTone } from "@/lib/format";
import type { ValidationData } from "@/lib/data";

// משטר תנודתיות גולמי → תווית + צבע (עקבי עם EngineView).
const REGIME_MAP: Record<string, { label: string; tone: string }> = {
  calm: { label: "רגוע", tone: "text-pos" },
  normal: { label: "רגיל", tone: "text-accent2" },
  volatile: { label: "תנודתי", tone: "text-neg" },
};
const regimeInfo = (r: string) => REGIME_MAP[r] ?? { label: "לא ידוע", tone: "text-text3" };

// שכבת "המנוע מול המציאות": משווה מה שהמנוע המליץ מול מה שבאמת הרוויח הכי הרבה,
// על פני כל הפקיעות שגם תועדו (decision_log) וגם נסגרו עם P&L (paper_trades).
export function ValidationSection({ validation }: { validation: ValidationData }) {
  const { rows, summary } = validation;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight">
          <Target className="text-accent" /> המנוע מול המציאות
        </h2>
        <p className="mt-0.5 text-xs text-text3">
          ולידציה קריאה-בלבד: החלטות המנוע מול הרווח האמיתי, לכל פקיעה שתועדה וגם נסגרה.
        </p>
      </div>

      {summary.nValidated === 0 ? (
        <Empty
          title="אין עדיין פקיעות לוַלִידציה"
          hint="פקיעה נכנסת לכאן כשיש לה גם החלטה מתועדת וגם עסקאות שנסגרו עם P&L."
        />
      ) : (
        <>
          {/* מדדי-על */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi
              label="אחוז פגיעה"
              value={pctFrac(summary.hitRate, 0)}
              tone="text-accent"
              sub={`${summary.nValidated} פקיעות שנוולדו`}
            />
            <Kpi
              label="תיק המנוע"
              value={money(summary.recommendedPnl)}
              tone={pnlTone(summary.recommendedPnl)}
              sub="לפי ההמלצה בפועל"
            />
            <Kpi
              label="התקרה (המושלם)"
              value={money(summary.bestPnl)}
              tone={pnlTone(summary.bestPnl)}
              sub="תמיד הטובה ביותר"
            />
            <Kpi
              label="חרטה מצטברת"
              value={ils(summary.totalRegret)}
              tone={summary.totalRegret > 0 ? "text-neg" : "text-text2"}
              sub="פער מהתקרה"
            />
          </div>

          {/* תובנת המפתח: המנוע מול בחירה אקראית */}
          <div className="rounded-xl border border-border bg-surface2/40 px-4 py-3 text-sm text-text2">
            <b className="text-text1">מנוע מול אקראי:</b> תיק המנוע הניב{" "}
            <span className={`font-semibold tabular-nums ${pnlTone(summary.recommendedPnl)}`}>
              {money(summary.recommendedPnl)}
            </span>{" "}
            מול{" "}
            <span className="font-semibold tabular-nums text-text2">{money(summary.avgPnl)}</span>{" "}
            של בחירה אקראית (ממוצע כל האסטרטגיות).{" "}
            {summary.recommendedPnl > summary.avgPnl
              ? "המנוע מוסיף ערך גם כשאינו פוגע בול."
              : "המנוע עדיין לא מכה את הבחירה האקראית."}
          </div>

          {/* טבלת פקיעות */}
          <Panel title="פירוט לפי פקיעה" sub="ההמלצה מול הטובה ביותר בפועל">
            <div className="overflow-x-auto">
              <table className="w-full text-right text-sm">
                <thead>
                  <tr className="text-xs text-text3">
                    <th className="pb-2 font-medium">פקיעה</th>
                    <th className="pb-2 font-medium">משטר</th>
                    <th className="pb-2 font-medium">המלצת המנוע</th>
                    <th className="pb-2 font-medium">P&L המלצה</th>
                    <th className="pb-2 font-medium">הטובה ביותר</th>
                    <th className="pb-2 font-medium">P&L מיטבי</th>
                    <th className="pb-2 font-medium">חרטה</th>
                    <th className="pb-2 font-medium">פגיעה</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const ri = regimeInfo(r.regime);
                    return (
                      <tr key={i} className="border-t border-border">
                        <td className="py-2.5 tabular-nums text-text2" dir="ltr">{r.expiry}</td>
                        <td className="py-2.5">
                          <span className={`inline-flex items-center gap-1.5 ${ri.tone}`}>
                            <Dot /> {ri.label}
                          </span>
                        </td>
                        <td className={`py-2.5 ${r.hit ? "font-semibold text-accent" : "text-text1"}`}>
                          {r.topStrategy}
                        </td>
                        <td className={`py-2.5 tabular-nums ${pnlTone(r.recommendedPnl)}`} dir="ltr">
                          {money(r.recommendedPnl)}
                        </td>
                        <td className="py-2.5 text-text2">{r.bestStrategy}</td>
                        <td className={`py-2.5 tabular-nums ${pnlTone(r.bestPnl)}`} dir="ltr">
                          {money(r.bestPnl)}
                        </td>
                        <td
                          className={`py-2.5 tabular-nums ${r.regret == null ? "text-text3" : r.regret > 0 ? "text-neg" : "text-text3"}`}
                          dir="ltr"
                        >
                          {r.regret == null ? "—" : r.regret === 0 ? "—" : ils(r.regret)}
                        </td>
                        <td className="py-2.5">
                          {r.hit ? (
                            <span className="font-semibold text-pos">✓</span>
                          ) : (
                            <span className="text-text3">✗</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-2 text-xs text-text3">
              נוולדו {summary.nValidated} פקיעות — לכל אחת החלטה מתועדת וגם עסקאות שנסגרו.
            </div>
          </Panel>

          {/* שקיפות */}
          <AccordionItem header={<span className="font-semibold">איך זה נמדד (שקיפות)</span>}>
            <ul className="space-y-2.5 text-sm text-text2">
              <li>
                <b className="text-text1">פגיעה (hit):</b> ההמלצה הניבה את ה-P&L הגבוה ביותר
                מבין כל 6 האסטרטגיות באותה פקיעה. תיקו על המקסימום נחשב פגיעה (השוואת ערך, לא מזהה).
              </li>
              <li>
                <b className="text-text1">חרטה (regret):</b> כמה עלתה הטעות — P&L של הטובה ביותר
                פחות P&L של ההמלצה. 0 כשפגע; מקף אם להמלצה לא נפתחה/נסגרה עסקה.
              </li>
              <li>
                <b className="text-text1">התקרה מול הרצפה:</b> המושלם = לבחור תמיד את הטובה ביותר;
                אקראי = ממוצע כל האסטרטגיות. המנוע מוסיף ערך אם הוא בין השניים וקרוב לתקרה.
              </li>
              <li>
                <b className="text-text1">מקור:</b> ההחלטה האחרונה שתועדה לכל פקיעה (decision_log)
                מול P&L אמיתי של עסקאות שנסגרו (paper_trades). קריאה-בלבד, אפס כתיבה.
              </li>
            </ul>
          </AccordionItem>
        </>
      )}
    </div>
  );
}
