import type { ReactNode } from "react";
import { card } from "@/lib/ui";

export function Panel({
  title,
  sub,
  children,
  className = "",
}: {
  title?: ReactNode;
  sub?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`${card} p-6 ${className}`}>
      {title && (
        <div className="mb-4">
          <h2 className="text-lg font-bold tracking-tight">{title}</h2>
          {sub && <p className="mt-0.5 text-sm text-text2">{sub}</p>}
        </div>
      )}
      {children}
    </section>
  );
}
