import type { ReactNode } from "react";
import { card } from "@/lib/ui";

export function Card({
  className = "",
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={`${card} ${className}`}>{children}</div>;
}
