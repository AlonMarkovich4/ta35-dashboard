import type { ReactNode } from "react";
import { card } from "@/lib/ui";

export function Kpi({
  icon,
  label,
  value,
  tone = "text-text1",
  sub,
  subTone = "text-text3",
}: {
  icon?: ReactNode;
  label: string;
  value: ReactNode;
  tone?: string;
  sub?: ReactNode;
  subTone?: string;
}) {
  return (
    <div className={`${card} flex items-center justify-between p-5`}>
      <div className="text-right">
        <div className="mb-1 text-xs text-text2">{label}</div>
        <div className={`text-2xl font-bold tabular-nums ${tone}`}>{value}</div>
        {sub != null && (
          <div className={`mt-0.5 text-[11px] ${subTone}`}>{sub}</div>
        )}
      </div>
      {icon && (
        <span className="grid h-11 w-11 place-items-center rounded-xl bg-surface2 text-xl text-accent">
          {icon}
        </span>
      )}
    </div>
  );
}
