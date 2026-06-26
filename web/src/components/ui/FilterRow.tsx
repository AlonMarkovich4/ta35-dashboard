"use client";

export function FilterRow<T extends string>({
  options,
  value,
  onPick,
}: {
  options: { v: T; l: string }[];
  value: T;
  onPick: (v: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const active = o.v === value;
        return (
          <button
            key={o.v}
            onClick={() => onPick(o.v)}
            className={`rounded-lg border px-3 py-1.5 text-xs transition ${
              active
                ? "border-accent/40 bg-accent/15 text-accent"
                : "border-border bg-surface2 text-text2 hover:text-text1"
            }`}
          >
            {o.l}
          </button>
        );
      })}
    </div>
  );
}
