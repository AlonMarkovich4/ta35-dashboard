"use client";

import Link from "next/link";
import { Kpi } from "@/components/ui/Kpi";
import { Panel } from "@/components/ui/Panel";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { card } from "@/lib/ui";
import { BarChart, Trending, Target, Calendar, Wallet, Cpu, Refresh } from "@/components/icons";
import type { HomeStatus } from "@/lib/data";

// תוכן סטטי (לא נתונים) — כרטיסי ניווט + הסבר המערכת
const NAV = [
  { href: "/historical", Icon: BarChart, title: "ניתוח היסטורי", desc: "התפלגות תנועות, % עליות/ירידות, פירוט לפי שנה וסוג פקיעה." },
  { href: "/strategies", Icon: Trending, title: "השוואת אסטרטגיות", desc: "Win Rate של 6 אסטרטגיות על 25 וריאנטים — grid search." },
  { href: "/upcoming", Icon: Target, title: "פקיעה קרובה", desc: "שרשרת אופציות עדכנית, זיהוי ATM, והמלצה מבוססת הקשר." },
  { href: "/events", Icon: Calendar, title: "אירועים והקשר", desc: "אירועים היסטוריים + ציון סיכון לפקיעה הקרובה." },
  { href: "/paper", Icon: Wallet, title: "מסחר נייר", desc: "תיקי דמו, פוזיציות, ו-P/L מסולק ופתוח." },
  { href: "/engine", Icon: Cpu, title: "מנוע החלטה", desc: "ההחלטה הנוכחית, דירוג אסטרטגיות, והיסטוריית החלטות." },
];

const ABOUT = [
  "מנתחת 965+ פקיעות היסטוריות של מדד TA-35 מ-2010 עד היום.",
  "מלבישה 6 אסטרטגיות אופציות (Iron Condor, Butterfly, Straddle ועוד) על כל פקיעה.",
  "מחשבת Win Rate לכל אסטרטגיה עם grid search על הפרמטרים המיטביים.",
  "מאתרת מקרים היסטוריים דומים לפקיעה הקרובה (סוג + עונתיות + תנועה אחרונה).",
  "מצליבה עם אירועים היסטוריים וחישוב ציון סיכון לפקיעה הקרובה.",
];

export function HomeView({ status }: { status: HomeStatus }) {
  const lastUpdate = status.lastUpdate ?? status.chainAsOf ?? "—";

  return (
    <div className="space-y-6">
      {/* hero */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">TA-35 Expiry Intelligence</h1>
          <p className="mt-1 text-sm text-text2">
            מערכת ניתוח הסתברותי של פקיעות מדד TA-35 — 965+ פקיעות היסטוריות, 6 אסטרטגיות אופציות.
          </p>
        </div>
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface/70 px-3 py-1.5 text-xs text-text2 backdrop-blur">
          <Refresh className="text-sm" /> עודכן לאחרונה: {lastUpdate}
        </span>
      </div>

      {/* system status */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">סטטוס מערכת</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi
            label="פקיעות היסטוריות"
            value={String(status.expiryCount)}
            sub={status.lastExpiry ? `עד ${status.lastExpiry}` : undefined}
          />
          <Kpi
            label="שרשרת אופציות"
            value={status.chainLoaded ? "טעונה" : "לא זמינה"}
            tone={status.chainLoaded ? "text-pos" : "text-text3"}
            sub={status.chainLoaded && status.chainAsOf ? status.chainAsOf : undefined}
          />
          <Kpi label="אירועים במסד" value={String(status.eventCount)} />
          <Kpi label="תאריך עדכון" value={lastUpdate} />
        </div>
      </div>

      {/* quick nav */}
      <div>
        <h2 className="mb-3 text-lg font-bold tracking-tight">ניווט מהיר</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {NAV.map(({ href, Icon, title, desc }) => (
            <Link
              key={href}
              href={href}
              className={`${card} group p-5 transition hover:border-accent/40 hover:bg-surface2/40`}
            >
              <span className="mb-3 grid h-10 w-10 place-items-center rounded-xl bg-surface2 text-accent">
                <Icon className="text-xl" />
              </span>
              <div className="font-bold text-text1">{title}</div>
              <div className="mt-1 text-sm text-text2">{desc}</div>
            </Link>
          ))}
        </div>
      </div>

      {/* what the system does */}
      <Panel title="מה המערכת עושה">
        <ul className="space-y-2 text-sm text-text2">
          {ABOUT.map((line, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-accent">•</span>
              <span>{line}</span>
            </li>
          ))}
        </ul>
      </Panel>

      <Disclaimer>כלי מחקר בלבד — אינו מהווה המלצת מסחר. אין אחריות לדיוק הנתונים.</Disclaimer>
    </div>
  );
}
