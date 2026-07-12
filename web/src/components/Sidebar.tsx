"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import {
  Home,
  BarChart,
  Trending,
  Target,
  Calendar,
  Wallet,
  Cpu,
  Spark,
  Sun,
  Moon,
  Logout,
} from "@/components/icons";

const NAV = [
  { href: "/", label: "סקירה", Icon: Home },
  { href: "/historical", label: "ניתוח היסטורי", Icon: BarChart },
  { href: "/strategies", label: "השוואת אסטרטגיות", Icon: Trending },
  { href: "/upcoming", label: "פקיעה קרובה", Icon: Target },
  { href: "/events", label: "אירועים והקשר", Icon: Calendar },
  { href: "/paper", label: "מסחר נייר", Icon: Wallet },
  { href: "/engine", label: "מנוע החלטה", Icon: Cpu },
  { href: "/margin", label: "מרווח אופטימלי", Icon: Spark },
];

// קוראים את ה-theme ישירות מ-class של <html> (מקור אמת יחיד) במקום state כפול
function subscribeTheme(onChange: () => void) {
  const mo = new MutationObserver(onChange);
  mo.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
  return () => mo.disconnect();
}

function useIsLight() {
  return useSyncExternalStore(
    subscribeTheme,
    () => document.documentElement.classList.contains("light"),
    () => false, // server snapshot — ברירת מחדל כהה (תואם לסקריפט ב-<head>)
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const light = useIsLight();

  const toggleTheme = () => {
    const isLight = document.documentElement.classList.toggle("light");
    try {
      localStorage.setItem("theme", isLight ? "light" : "dark");
    } catch {}
  };

  return (
    <aside className="fixed right-0 top-0 bottom-0 z-20 flex w-14 flex-col items-center justify-between border-l border-border bg-surface/70 py-4 backdrop-blur">
      <nav className="flex flex-col items-center gap-1">
        {NAV.map(({ href, label, Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={label}
              aria-label={label}
              className={`grid h-10 w-10 place-items-center rounded-lg transition ${
                active
                  ? "bg-accent/15 text-accent ring-1 ring-accent/30"
                  : "text-text3 hover:bg-surface2 hover:text-text1"
              }`}
            >
              <Icon className="text-xl" />
            </Link>
          );
        })}
      </nav>

      <div className="flex flex-col items-center gap-1">
        <button
          onClick={toggleTheme}
          title="החלף theme"
          aria-label="החלף theme"
          className="grid h-10 w-10 place-items-center rounded-lg text-text3 transition hover:bg-surface2 hover:text-text1"
        >
          {light ? <Moon className="text-xl" /> : <Sun className="text-xl" />}
        </button>
        <button
          title="יציאה"
          aria-label="יציאה"
          className="grid h-10 w-10 place-items-center rounded-lg text-text3 transition hover:bg-surface2 hover:text-text1"
        >
          <Logout className="text-xl" />
        </button>
      </div>
    </aside>
  );
}
