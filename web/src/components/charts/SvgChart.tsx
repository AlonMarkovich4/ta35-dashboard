import type { ReactNode } from "react";

export function SvgChart({
  w,
  h,
  label,
  minW = 640,
  children,
}: {
  w: number;
  h: number;
  label: string;
  minW?: number;
  children: ReactNode;
}) {
  return (
    <div dir="ltr" className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full"
        style={{ minWidth: minW }}
        role="img"
        aria-label={label}
      >
        <title>{label}</title>
        {children}
      </svg>
    </div>
  );
}
