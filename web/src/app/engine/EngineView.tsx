"use client";

import { Panel } from "@/components/ui/Panel";
import { Kpi } from "@/components/ui/Kpi";
import { AccordionItem } from "@/components/ui/Accordion";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Empty } from "@/components/ui/Empty";
import { Cpu, Calendar, Dot } from "@/components/icons";
import { pctFrac, signedPctFrac } from "@/lib/format";
import { ValidationSection } from "./ValidationSection";
import type { CurrentDecision, DecisionLogRow, ValidationData } from "@/lib/data";

// משטר תנודתיות גולמי → תווית + צבע; כל ערך אחר → "לא ידוע".
const REGIME_MAP: Record<string, { label: string; tone: string }> = {
  calm: { label: "רגוע", tone: "text-pos" },
  normal: { label: "רגיל", tone: "text-accent2" },
  volatile: { label: "תנודתי", tone: "text-neg" },
};
const regimeInfo = (r: string) => REGIME_MAP[r] ?? { label: "לא ידוע", tone: "text-text3" };

export function EngineView({
  decision,
  logs,
  validation,
}: {
  decision: CurrentDecision | null;
  logs: DecisionLogRow[];
  validation: ValidationData;
}) {
  return (
    <div className="space-y-6">
      <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
        <Cpu className="text-accent" /> מנוע ההחלטה
      </h1>

      {/* shadow mode banner */}
      <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-sm">
        <span className="font-bold text-warn">
          Shadow Mode — המנוע ממליץ ומתעד, לא פותח עסקאות
        </span>
        <span className="text-text2">
          {" "}
          — כל 6 התיקים נפתחים בכל מקרה. כלי מחקר בלבד, לא ייעוץ השקעות.
        </span>
      </div>

      {/* Part A — current decision */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-bold tracking-tight">ההחלטה הנוכחית</h2>
          {decision && (
            <p className="mt-0.5 text-xs text-text3">
              פקיעה קרובה: {decision.expiry} ({decision.expiryType}) — מתועד {decision.decidedAt}
            </p>
          )}
        </div>

        {!decision ? (
          <Empty title="אין החלטה מתועדת עדיין" hint="המנוע יתעד החלטה עבור הפקיעה הקרובה." />
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi label="פקיעה" value={decision.expiry} sub={`סוג ${decision.expiryType}`} />
              <Kpi
                label="משטר תנודתיות"
                value={
                  <span className={`inline-flex items-center gap-1.5 ${regimeInfo(decision.regime).tone}`}>
                    <Dot /> {regimeInfo(decision.regime).label}
                  </span>
                }
              />
              <Kpi
                label="ציון סיכון"
                value={decision.riskScore == null ? "—" : `${decision.riskScore.toFixed(1)}/10`}
                tone="text-warn"
              />
              <Kpi label="מקרים דומים" value={decision.nSimilar == null ? "—" : String(decision.nSimilar)} />
            </div>

            {decision.note && (
              <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-sm text-text2">
                <b className="text-warn">הערת מנוע:</b> {decision.note}
              </div>
            )}

            <Panel title="דירוג אסטרטגיות" sub="מדורג לפי Win Rate מותנה ועוצמה (שובר-שוויון)">
              {decision.ranking.length === 0 ? (
                <p className="text-sm text-text3">אין דירוג אסטרטגיות בהחלטה זו.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-right text-sm">
                    <thead>
                      <tr className="text-xs text-text3">
                        <th className="pb-2 font-medium">#</th>
                        <th className="pb-2 font-medium">אסטרטגיה</th>
                        <th className="pb-2 font-medium">WR מותנה</th>
                        <th className="pb-2 font-medium">WR גלובלי</th>
                        <th className="pb-2 font-medium">Δ</th>
                        <th className="pb-2 font-medium">עוצמה</th>
                      </tr>
                    </thead>
                    <tbody>
                      {decision.ranking.map((r) => {
                        const top = r.rank === 1;
                        const delta = r.deltaWr;
                        return (
                          <tr
                            key={r.rank}
                            className={`border-t border-border ${top ? "bg-accent/10 font-semibold" : ""}`}
                          >
                            <td className="py-2.5 tabular-nums text-text3">{r.rank}</td>
                            <td className={`py-2.5 ${top ? "text-accent" : "text-text1"}`}>{r.strategy}</td>
                            <td className="py-2.5 tabular-nums">{pctFrac(r.condWr, 0)}</td>
                            <td className="py-2.5 tabular-nums text-text2">{pctFrac(r.globalWr, 0)}</td>
                            <td
                              className={`py-2.5 tabular-nums ${delta == null ? "text-text3" : delta >= 0 ? "text-pos" : "text-neg"}`}
                              dir="ltr"
                            >
                              {signedPctFrac(delta, 1)}
                            </td>
                            <td className="py-2.5 tabular-nums text-text2">
                              {r.intensity == null ? "—" : r.intensity.toFixed(2)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>

            {decision.ranking.length > 0 && (
              <AccordionItem header={<span className="font-semibold">נימוקי הדירוג</span>}>
                <div className="space-y-2 text-sm">
                  {decision.ranking.map((r) => (
                    <div key={r.rank}>
                      <span className="font-semibold text-text1">
                        #{r.rank} · {r.strategy}
                      </span>
                      {r.reason && <span className="text-text2"> — {r.reason}</span>}
                    </div>
                  ))}
                </div>
              </AccordionItem>
            )}
          </>
        )}
      </div>

      {/* Recorder — visual, disabled (backend pending) */}
      <Panel title={<span className="flex items-center gap-2"><Cpu className="text-text2" /> תיעוד ידני (Recorder)</span>}>
        <button
          disabled
          className="cursor-not-allowed rounded-lg border border-border bg-surface2 px-4 py-2 text-sm text-text3 opacity-60"
        >
          הרץ מנוע ותעד החלטה עכשיו
        </button>
        <p className="mt-2 text-xs text-text3">
          התיעוד רץ אוטומטית (scheduled). הפעלה ידנית תתחבר ל-backend בהמשך.
        </p>
      </Panel>

      {/* Validation — engine vs reality ("המנוע מול המציאות") */}
      <ValidationSection validation={validation} />

      {/* Part B — explanation */}
      <AccordionItem header={<span className="font-semibold">מה כל מדד אומר (שקיפות)</span>}>
        <ul className="space-y-2.5 text-sm text-text2">
          <li>
            <b className="text-text1">Win Rate (מותנה / גלובלי):</b> באיזו תדירות
            היסטורית תנועת הפקיעה נפלה בטווח שבו האסטרטגיה מנצחת. מותנה = פקיעות דומות
            (סוג/חודש/תנועה קודמת); גלובלי = כל ההיסטוריה. זו הסתברות-טווח, לא רווח כספי.
          </li>
          <li>
            <b className="text-text1">Δ:</b> ההפרש בין המותנה לגלובלי — כמה ההקשר
            הנוכחי משפר או מרע את הסיכוי.
          </li>
          <li>
            <b className="text-text1">עוצמה (cond_intensity):</b> כמה עמוק בתוך אזור
            הרווח נפלה התנועה בממוצע על הפקיעות הדומות. 1.0 = אופטימלי, 0 = בקצה. משמש
            כשובר-שוויון בין אסטרטגיות עם אותו Win Rate.
          </li>
          <li>
            <b className="text-text1">משטר תנודתיות:</b> התנודתיות האחרונה מול הממוצע
            ההיסטורי — רגוע / רגיל / תנודתי.
          </li>
          <li>
            <b className="text-text1">Shadow Mode:</b> בשלב זה המנוע ממליץ ומתעד בלבד —
            כל 6 התיקים נפתחים בכל מקרה.
          </li>
        </ul>
      </AccordionItem>

      {/* Part C — history */}
      <div className="space-y-3">
        <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight">
          <Calendar className="text-text2" /> היסטוריית ההחלטות
        </h2>
        {logs.length === 0 ? (
          <Empty title="אין היסטוריית החלטות" hint="החלטות מתועדות יופיעו כאן." />
        ) : (
          <Panel>
            <div className="overflow-x-auto">
              <table className="w-full text-right text-sm">
                <thead>
                  <tr className="text-xs text-text3">
                    <th className="pb-2 font-medium">מתי</th>
                    <th className="pb-2 font-medium">פקיעה</th>
                    <th className="pb-2 font-medium">סוג</th>
                    <th className="pb-2 font-medium">משטר</th>
                    <th className="pb-2 font-medium">אסטרטגיה מובילה</th>
                    <th className="pb-2 font-medium">מקרים דומים</th>
                    <th className="pb-2 font-medium">סיכון</th>
                    <th className="pb-2 font-medium">טריגר</th>
                    <th className="pb-2 font-medium">גרסה</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((d, i) => {
                    const ri = regimeInfo(d.regime);
                    return (
                      <tr key={i} className="border-t border-border">
                        <td className="py-2 tabular-nums text-text3" dir="ltr">{d.when}</td>
                        <td className="py-2 tabular-nums text-text2">{d.expiry}</td>
                        <td className="py-2 text-text2">{d.type}</td>
                        <td className="py-2">
                          <span className={`inline-flex items-center gap-1.5 ${ri.tone}`}>
                            <Dot /> {ri.label}
                          </span>
                        </td>
                        <td className="py-2 text-text1">{d.topStrategy}</td>
                        <td className="py-2 tabular-nums text-text2">{d.nSimilar == null ? "—" : d.nSimilar}</td>
                        <td className="py-2 tabular-nums text-text2">{d.risk == null ? "—" : d.risk.toFixed(1)}</td>
                        <td className="py-2 text-text3">{d.trigger}</td>
                        <td className="py-2 text-text3" dir="ltr">{d.version}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-2 text-xs text-text3">
              מוצגות {logs.length} ההחלטות האחרונות (append-only; decided_at מבדיל בין הרצות).
            </div>
          </Panel>
        )}
      </div>

      <Disclaimer>
        כלי מחקר בלבד — לא ייעוץ השקעות. Shadow mode: המנוע מציג ומתעד, לא מבצע.
      </Disclaimer>
    </div>
  );
}
