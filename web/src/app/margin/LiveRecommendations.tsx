"use client";

import { Fragment, useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { Empty } from "@/components/ui/Empty";
import { Target, ChevronDown } from "@/components/icons";
import { pct, pctFrac, ils, en, money } from "@/lib/format";
import { PayoffChart } from "./PayoffChart";
import type { MarginLiveRow } from "@/lib/data";

// טבלת ההמלצות החיות — כל שורה נלחצת ופותחת מתחתיה גרף Payoff (expand/collapse, סגור כברירת מחדל).
export function LiveRecommendations({ live }: { live: MarginLiveRow[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const COLS = 12;   // +1: "תנועה צפויה (שוק)"

  return (
    <div className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight">
          <Target className="text-accent" /> ההמלצות החיות
        </h2>
        <p className="mt-0.5 text-xs text-text3">
          ההמלצה האחרונה לכל פקיעה קרובה (גרסה margin-v1.1). כל שורה = טרפז מלא של 4 רגליים:
          מכירת 2 רגליים (short) וקניית 2 הגנות (long) במרחק הכנף מעבר לרגל המכורה — הכנף הרשמית
          0.75%. לחצו על שורה לפתיחת גרף ה-Payoff.
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
                  <th className="pb-2 font-medium" aria-label="פתח גרף" />
                  <th className="pb-2 font-medium">פקיעה</th>
                  <th className="pb-2 font-medium">מרווח מומלץ</th>
                  <th
                    className="pb-2 font-medium"
                    title="מחושב ממחיר ה-straddle — כמה תנועה השוק מתמחר לפקיעה"
                  >
                    תנועה צפויה (שוק)
                  </th>
                  <th className="pb-2 font-medium">hold משוקלל</th>
                  <th className="pb-2 font-medium">hold מותנה</th>
                  <th className="pb-2 font-medium">hold גלובלי</th>
                  <th className="pb-2 font-medium">פרמיה צפויה</th>
                  <th className="pb-2 font-medium">מכור (short)</th>
                  <th className="pb-2 font-medium">קנה (long)</th>
                  <th className="pb-2 font-medium">כנף</th>
                  <th className="pb-2 font-medium">הפסד-מקס</th>
                </tr>
              </thead>
              <tbody>
                {live.map((r, i) => {
                  const isOpen = open === i;
                  const toggle = () => setOpen(isOpen ? null : i);
                  return (
                    <Fragment key={i}>
                      <tr
                        className="cursor-pointer border-t border-border hover:bg-surface2/40"
                        onClick={toggle}
                      >
                        <td className="py-2.5 pl-1 text-text3">
                          <ChevronDown
                            className={`transition-transform ${isOpen ? "" : "-rotate-90"}`}
                          />
                        </td>
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
                        {/* תנועה צפויה (שוק) — מה-straddle. סימון עדין כשהשוק מתמחר
                            תנועה גדולה מהמרווח (implied_vs_margin > 1): המרווח עלול להישבר.
                            תיעוד בלבד — לא משפיע על בחירת המרווח. */}
                        <td className="py-2.5 tabular-nums" dir="ltr">
                          {r.impliedMovePct == null ? (
                            <span className="text-text3">—</span>
                          ) : (
                            <span
                              className={
                                r.impliedVsMargin != null && r.impliedVsMargin > 1
                                  ? "font-semibold text-warn"
                                  : "text-text2"
                              }
                              title={
                                r.impliedVsMargin == null
                                  ? undefined
                                  : `השוק מתמחר ${r.impliedVsMargin.toFixed(2)}× מהמרווח המומלץ`
                              }
                            >
                              {pct(r.impliedMovePct, 2)}
                              {r.impliedVsMargin != null && r.impliedVsMargin > 1 && (
                                <span className="mr-1 text-[10px]" title="השוק מצפה לתנועה גדולה מהמרווח">
                                  ⚠
                                </span>
                              )}
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
                        <td className="py-2.5 tabular-nums text-text2" dir="ltr">
                          {r.legsSource === "none" ? (
                            "—"
                          ) : (
                            <>
                              {en(r.longPutStrike)}P / {en(r.longCallStrike)}C
                              {r.legsSource === "computed" && (
                                <span className="text-[10px] text-text3"> (מחושב)</span>
                              )}
                            </>
                          )}
                        </td>
                        <td className="py-2.5 tabular-nums text-text2">{pct(r.wingPct, 2)}</td>
                        <td className="py-2.5 tabular-nums text-neg" dir="ltr">{money(r.maxLoss)}</td>
                      </tr>
                      {r.reason && (
                        <tr className="cursor-pointer" onClick={toggle}>
                          <td colSpan={COLS} className="pb-3 pt-0 pr-6 text-xs text-text3">
                            ➜ {r.reason}
                          </td>
                        </tr>
                      )}
                      {isOpen && (
                        <tr>
                          <td colSpan={COLS} className="pb-4 pt-1">
                            <PayoffChart
                              longPutStrike={r.longPutStrike}
                              shortPutStrike={r.shortPutStrike}
                              shortCallStrike={r.shortCallStrike}
                              longCallStrike={r.longCallStrike}
                              netPremium={r.premiumIls}
                              maxLoss={r.maxLoss}
                              baseIndex={r.baseIndex}
                              wingPct={r.wingPct}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-xs text-text3">
            מוצגות {live.length} פקיעות קרובות · עודכן לאחרונה {live[0]?.recommendedAt} · לחצו על שורה לגרף Payoff.
          </div>
        </Panel>
      )}
    </div>
  );
}
