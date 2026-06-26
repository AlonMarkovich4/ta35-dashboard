import type { ReactNode } from "react";

export function Disclaimer({ children }: { children?: ReactNode }) {
  return (
    <p className="pt-1 text-xs text-text3">
      ⚠️{" "}
      {children ??
        "כלי מחקר בלבד — לא ייעוץ השקעות. כל הנתונים הם סימולציה/ניתוח היסטורי בלבד."}
    </p>
  );
}
