export type TrackRow = {
  name: string;
  total: number;
  wins: number;
  winRate: number;
  totalPnl: number;
  avgPnl: number;
};

const money = (v: number) =>
  `${v > 0 ? "+" : v < 0 ? "-" : ""}₪${Math.abs(Math.round(v)).toLocaleString("en-US")}`;
const pnlTone = (v: number) => (v > 0 ? "text-pos" : v < 0 ? "text-neg" : "text-text2");

export function TrackRecord({ records }: { records: TrackRow[] }) {
  if (!records.length) return <p className="text-sm text-text3">עדיין אין עסקאות סגורות לניתוח.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-right text-sm">
        <thead>
          <tr className="text-xs text-text3">
            <th className="pb-2 font-medium">אסטרטגיה</th>
            <th className="pb-2 font-medium">עסקאות</th>
            <th className="pb-2 font-medium">רווחיות</th>
            <th className="pb-2 font-medium">Win Rate</th>
            <th className="pb-2 font-medium">סה״כ PnL</th>
            <th className="pb-2 font-medium">ממוצע PnL</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => (
            <tr key={r.name} className="border-t border-border">
              <td className="py-2.5 font-medium text-text1">{r.name}</td>
              <td className="py-2.5 tabular-nums text-text2">{r.total}</td>
              <td className="py-2.5 tabular-nums text-text2">{r.wins}</td>
              <td className="py-2.5 tabular-nums text-text2">{Math.round(r.winRate * 100)}%</td>
              <td className={`py-2.5 tabular-nums font-semibold ${pnlTone(r.totalPnl)}`} dir="ltr">{money(r.totalPnl)}</td>
              <td className={`py-2.5 tabular-nums ${pnlTone(r.avgPnl)}`} dir="ltr">{money(r.avgPnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
