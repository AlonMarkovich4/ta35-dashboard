"use client";

import { useState, type ReactNode } from "react";
import { card } from "@/lib/ui";
import { ChevronDown } from "@/components/icons";

export function AccordionItem({
  header,
  children,
  defaultOpen = false,
}: {
  header: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`${card} overflow-hidden`}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 p-4 text-right transition hover:bg-surface2/40"
      >
        <div className="flex-1">{header}</div>
        <ChevronDown
          className={`shrink-0 text-text3 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="border-t border-border p-4">{children}</div>}
    </div>
  );
}
