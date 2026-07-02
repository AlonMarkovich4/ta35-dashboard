import type { ReactNode } from "react";
import { Sidebar } from "@/components/Sidebar";
import { Spark } from "@/components/icons";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <>
      <Sidebar />
      <div className="pr-14">
        <header className="mx-auto flex max-w-[1400px] items-center gap-2 px-6 py-5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-surface2 text-accent">
            <Spark className="text-lg" />
          </span>
          <span className="text-lg font-bold tracking-tight">TA-35</span>
        </header>
        <main className="mx-auto max-w-[1400px] px-6 pb-16">{children}</main>
      </div>
    </>
  );
}
