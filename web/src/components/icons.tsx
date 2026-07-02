import type { ReactNode } from "react";

const base =
  (d: ReactNode, vb = "0 0 24 24") =>
  function Icon(p: { className?: string }) {
    return (
      <svg
        viewBox={vb}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.7}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={p.className}
        width="1em"
        height="1em"
        aria-hidden="true"
      >
        {d}
      </svg>
    );
  };

export const Home = base(<><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /></>);
export const BarChart = base(<><path d="M3 21h18" /><path d="M7 21V10" /><path d="M12 21V4" /><path d="M17 21V14" /></>);
export const Trending = base(<><path d="M3 17l6-6 4 4 8-8" /><path d="M17 7h4v4" /></>);
export const Target = base(<><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" /></>);
export const Calendar = base(<><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18" /><path d="M8 3v4" /><path d="M16 3v4" /></>);
export const Sun = base(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="M5 5l1.4 1.4" /><path d="M17.6 17.6 19 19" /><path d="M19 5l-1.4 1.4" /><path d="M6.4 17.6 5 19" /></>);
export const Moon = base(<path d="M21 12.5A8.5 8.5 0 1 1 11.5 3 7 7 0 0 0 21 12.5z" />);
export const Logout = base(<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></>);
export const ChevronDown = base(<path d="M6 9l6 6 6-6" />);
export const Refresh = base(<><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 4v5h-5" /></>);
export const ArrowLeft = base(<><path d="M19 12H5" /><path d="M12 19l-7-7 7-7" /></>);
export const Spark = base(<path d="M13 2 4 14h7l-1 8 9-12h-7z" />);
export const Wallet = base(<><rect x="3" y="6" width="18" height="13" rx="2.5" /><path d="M3 10h18" /><circle cx="16.5" cy="14.5" r="1.3" /></>);
export const Cpu = base(<><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v3" /><path d="M15 2v3" /><path d="M9 19v3" /><path d="M15 19v3" /><path d="M2 9h3" /><path d="M2 15h3" /><path d="M19 9h3" /><path d="M19 15h3" /></>);
export const Bell = base(<><path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6z" /><path d="M10 20a2 2 0 0 0 4 0" /></>);
export const Wrench = base(<path d="M14.5 6.5a3.8 3.8 0 0 0-5 5L3.5 17.5 6.5 20.5l6-6a3.8 3.8 0 0 0 5-5l-2.2 2.2-2.6-.6-.6-2.6z" />);
export const Sprout = base(<><path d="M12 20v-8" /><path d="M12 12C12 9 10 7 7 7c0 3 2 5 5 5z" /><path d="M12 13c0-3 2-5 5-5 0 3-2 5-5 5z" /></>);
export const Trash = base(<><path d="M4 7h16" /><path d="M9 7V5h6v2" /><path d="M6 7l1 13h10l1-13" /></>);
export const Plus = base(<><path d="M12 5v14" /><path d="M5 12h14" /></>);

// נקודת סטטוס מלאה (לא stroke) — צבע נשלט ע"י text-*
export const Dot = (p: { className?: string }) => (
  <svg viewBox="0 0 12 12" width="0.7em" height="0.7em" className={p.className} aria-hidden="true">
    <circle cx="6" cy="6" r="5" fill="currentColor" />
  </svg>
);
