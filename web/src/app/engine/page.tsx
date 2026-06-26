import { Panel } from "@/components/ui/Panel";
import { Kpi } from "@/components/ui/Kpi";
import { AccordionItem } from "@/components/ui/Accordion";

// ─── Mock (נאמן-צורה; יוחלף ב-Supabase בשלב 4) ──────────────────────
const DECISION = {
  expiry: "02/07/2026",
  type: "W",
  source: "פקיעה קרובה אמיתית",
  regime: { dot: "🔵", label: "רגיל", tone: "text-accent2" },
  riskScore: 4.2,
  nSimilar: 12,
};

type Rank = {
  rank: number;
  name: string;
  condWr: number;
  globalWr: number;
  intensity: number;
  reason: string;
};

const RANKING: Rank[] = [
  { rank: 1, name: "Short Iron Condor", condWr: 0.78, globalWr: 0.73, intensity: 0.82,
    reason: "Win Rate מותנה גבוה ועוצמה 0.82 — התנועות הדומות נפלו עמוק בתוך אזור הרווח." },
  { rank: 2, name: "Long Call Butterfly", condWr: 0.61, globalWr: 0.58, intensity: 0.74,
    reason: "מותנה מעל הגלובלי; עוצמה גבוהה מצביעה על פקיעות קרובות ל-ATM." },
  { rank: 3, name: "Long Put Butterfly", condWr: 0.59, globalWr: 0.56, intensity: 0.71,
    reason: "דומה ל-Call Butterfly, מעט נמוך יותר בהקשר הנוכחי." },
  { rank: 4, name: "Long Straddle", condWr: 0.55, globalWr: 0.62, intensity: 0.40,
    reason: "ההקשר הנוכחי פחות תנודתי מהממוצע — מוריד את הסיכוי לתנועה חזקה." },
  { rank: 5, name: "Bull Call Spread", condWr: 0.50, globalWr: 0.52, intensity: 0.55,
    reason: "אסטרטגיה תלוית-כיוון; ההקשר ניטרלי ולכן ללא יתרון." },
  { rank: 6, name: "Long Strangle", condWr: 0.42, globalWr: 0.47, intensity: 0.33,
    reason: "דורש תנועה גדולה לשבירה; פחות סביר בהקשר הנוכחי." },
];

const REGIME = {
  calm: { dot: "🟢", label: "רגוע" },
  normal: { dot: "🔵", label: "רגיל" },
  volatile: { dot: "🔴", label: "תנודתי" },
} as const;

type Log = {
  at: string;
  expiry: string;
  type: string;
  regime: keyof typeof REGIME;
  top: string;
  nSim: number;
  risk: number;
  trigger: string;
  version: string;
};

const LOG: Log[] = [
  { at: "2026-06-25 09:00", expiry: "02/07/2026", type: "W", regime: "normal",   top: "Short Iron Condor",   nSim: 12, risk: 4.2, trigger: "scheduled", version: "v1.0" },
  { at: "2026-06-18 09:00", expiry: "25/06/2026", type: "W", regime: "calm",     top: "Long Call Butterfly", nSim: 9,  risk: 3.1, trigger: "scheduled", version: "v1.0" },
  { at: "2026-06-11 09:00", expiry: "18/06/2026", type: "W", regime: "volatile", top: "Long Straddle",       nSim: 7,  risk: 6.8, trigger: "scheduled", version: "v1.0" },
  { at: "2026-05-28 09:00", expiry: "31/05/2026", type: "M", regime: "normal",   top: "Short Iron Condor",   nSim: 15, risk: 4.5, trigger: "scheduled", version: "v1.0" },
  { at: "2026-05-21 09:00", expiry: "28/05/2026", type: "W", regime: "calm",     top: "Long Put Butterfly",  nSim: 11, risk: 2.9, trigger: "scheduled", version: "v1.0" },
  { at: "2026-05-14 09:00", expiry: "21/05/2026", type: "W", regime: "normal",   top: "Short Iron Condor",   nSim: 13, risk: 4.0, trigger: "manual",    version: "v1.0" },
];

const pct0 = (v: number) => `${Math.round(v * 100)}%`;
const signed = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

export default function EnginePage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">🧭 מנוע ההחלטה</h1>

      {/* shadow mode banner */}
      <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-sm">
        <span className="font-bold text-warn">
          🧭 Shadow Mode — המנוע ממליץ ומתעד, לא פותח עסקאות
        </span>
        <span className="text-text2">
          {" "}
          — כל 6 התיקים נפתחים בכל מקרה. כלי מחקר בלבד, לא ייעוץ השקעות.
        </span>
      </div>

      {/* Part A */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-bold tracking-tight">ההחלטה הנוכחית</h2>
          <p className="mt-0.5 text-xs text-text3">
            פקיעה קרובה: {DECISION.expiry} ({DECISION.type}) — {DECISION.source}
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi label="פקיעה" value={DECISION.expiry} sub={`סוג ${DECISION.type}`} />
          <Kpi
            label="משטר תנודתיות"
            value={
              <span className={DECISION.regime.tone}>
                {DECISION.regime.dot} {DECISION.regime.label}
              </span>
            }
          />
          <Kpi label="ציון סיכון" value={`${DECISION.riskScore.toFixed(1)}/10`} tone="text-warn" />
          <Kpi label="מקרים דומים" value={String(DECISION.nSimilar)} />
        </div>

        <Panel title="דירוג אסטרטגיות" sub="מדורג לפי Win Rate מותנה ועוצמה (שובר-שוויון)">
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
                {RANKING.map((r) => {
                  const delta = r.condWr - r.globalWr;
                  const top = r.rank === 1;
                  return (
                    <tr
                      key={r.rank}
                      className={`border-t border-border ${top ? "bg-accent/10 font-semibold" : ""}`}
                    >
                      <td className="py-2.5 tabular-nums text-text3">{r.rank}</td>
                      <td className={`py-2.5 ${top ? "text-accent" : "text-text1"}`}>{r.name}</td>
                      <td className="py-2.5 tabular-nums">{pct0(r.condWr)}</td>
                      <td className="py-2.5 tabular-nums text-text2">{pct0(r.globalWr)}</td>
                      <td
                        className={`py-2.5 tabular-nums ${delta >= 0 ? "text-pos" : "text-neg"}`}
                        dir="ltr"
                      >
                        {signed(delta)}
                      </td>
                      <td className="py-2.5 tabular-nums text-text2">{r.intensity.toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>

        <AccordionItem header={<span className="font-semibold">📝 נימוקי הדירוג</span>}>
          <div className="space-y-2 text-sm">
            {RANKING.map((r) => (
              <div key={r.rank}>
                <span className="font-semibold text-text1">
                  #{r.rank} · {r.name}
                </span>
                <span className="text-text2"> — {r.reason}</span>
              </div>
            ))}
          </div>
        </AccordionItem>
      </div>

      {/* Part B — explanation */}
      <AccordionItem header={<span className="font-semibold">ℹ️ מה כל מדד אומר (שקיפות)</span>}>
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
            ההיסטורי — 🟢 רגוע / 🔵 רגיל / 🔴 תנודתי.
          </li>
          <li>
            <b className="text-text1">Shadow Mode:</b> בשלב זה המנוע ממליץ ומתעד בלבד —
            כל 6 התיקים נפתחים בכל מקרה.
          </li>
        </ul>
      </AccordionItem>

      {/* Part C — history */}
      <div className="space-y-3">
        <h2 className="text-lg font-bold tracking-tight">🗂️ היסטוריית ההחלטות</h2>
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
                {LOG.map((d, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-2 tabular-nums text-text3" dir="ltr">{d.at}</td>
                    <td className="py-2 tabular-nums text-text2">{d.expiry}</td>
                    <td className="py-2 text-text2">{d.type}</td>
                    <td className="py-2 text-text2">
                      {REGIME[d.regime].dot} {REGIME[d.regime].label}
                    </td>
                    <td className="py-2 text-text1">{d.top}</td>
                    <td className="py-2 tabular-nums text-text2">{d.nSim}</td>
                    <td className="py-2 tabular-nums text-text2">{d.risk.toFixed(1)}</td>
                    <td className="py-2 text-text3">{d.trigger}</td>
                    <td className="py-2 text-text3" dir="ltr">{d.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-xs text-text3">
            מוצגות {LOG.length} ההחלטות האחרונות (append-only; decided_at מבדיל בין הרצות).
          </div>
        </Panel>
      </div>

      <p className="pt-1 text-xs text-text3">
        ⚠️ כלי מחקר בלבד — לא ייעוץ השקעות. Shadow mode: המנוע מציג ומתעד, לא מבצע.
      </p>
    </div>
  );
}
