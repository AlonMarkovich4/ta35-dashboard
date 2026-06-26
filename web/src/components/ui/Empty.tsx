import { card } from "@/lib/ui";

export function Empty({
  title = "אין עדיין נתונים",
  hint,
}: {
  title?: string;
  hint?: string;
}) {
  return (
    <div className={`${card} p-12 text-center`}>
      <div className="text-text2">{title}</div>
      {hint && <div className="mt-1 text-sm text-text3">{hint}</div>}
    </div>
  );
}
