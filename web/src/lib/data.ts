import "server-only";
import { sql } from "@/lib/db";

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    console.error("[data]", e);
    return fallback;
  }
}

const fmtDate = (d: string | Date) => {
  const dt = typeof d === "string" ? new Date(d) : d;
  // Pin the timezone so DATE columns (UTC midnight) don't render a day early
  // on runtimes behind UTC (e.g. Render), matching fmtDateTime below.
  return dt.toLocaleDateString("en-GB", {
    timeZone: "Asia/Jerusalem",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
};

// ─── events ─────────────────────────────────────────────────────────

export type EventRow = { id: number; date: string; cat: string; name: string; desc: string };

export async function getEvents(): Promise<EventRow[]> {
  return safe(async () => {
    const rows = await sql<
      { id: number; event_date: string; category: string | null; name: string; description: string | null }[]
    >`
      SELECT id, event_date, category, name, description
      FROM events
      ORDER BY event_date DESC
    `;
    return rows.map((r) => ({
      id: r.id,
      date: fmtDate(r.event_date),
      cat: r.category ?? "אחר",
      name: r.name,
      desc: r.description ?? "",
    }));
  }, []);
}

// ─── impact (עם/בלי אירוע בחלון 7 ימים) ────────────────────────────

export type Impact = {
  withEvent: number;
  withoutEvent: number;
  avgWith: number;
  avgWithout: number;
  gt2With: number;   // % פקיעות >2% מתוך "עם אירוע"
  gt2Without: number;
  lt1With: number;   // % פקיעות <1% מתוך "עם אירוע"
};

export async function getEventImpact(): Promise<Impact | null> {
  return safe(async () => {
    const [r] = await sql<
      {
        with_event: number; without_event: number;
        avg_with: number | null; avg_without: number | null;
        gt2_with: number | null; gt2_without: number | null; lt1_with: number | null;
      }[]
    >`
      WITH flagged AS (
        SELECT
          h.abs_move_pct,
          EXISTS (
            SELECT 1 FROM events e
            WHERE e.event_date BETWEEN h.expiry_date::date - INTERVAL '7 days'
                                   AND h.expiry_date::date
          ) AS has_event
        FROM expiry_history h
        WHERE h.abs_move_pct IS NOT NULL
      )
      SELECT
        COUNT(*) FILTER (WHERE has_event)                                        AS with_event,
        COUNT(*) FILTER (WHERE NOT has_event)                                    AS without_event,
        AVG(abs_move_pct) FILTER (WHERE has_event)                               AS avg_with,
        AVG(abs_move_pct) FILTER (WHERE NOT has_event)                           AS avg_without,
        100.0 * COUNT(*) FILTER (WHERE has_event AND abs_move_pct > 2)
              / NULLIF(COUNT(*) FILTER (WHERE has_event), 0)                     AS gt2_with,
        100.0 * COUNT(*) FILTER (WHERE NOT has_event AND abs_move_pct > 2)
              / NULLIF(COUNT(*) FILTER (WHERE NOT has_event), 0)                 AS gt2_without,
        100.0 * COUNT(*) FILTER (WHERE has_event AND abs_move_pct < 1)
              / NULLIF(COUNT(*) FILTER (WHERE has_event), 0)                     AS lt1_with
      FROM flagged
    `;
    if (!r) return null;
    return {
      withEvent: Number(r.with_event),
      withoutEvent: Number(r.without_event),
      avgWith: Number(r.avg_with ?? 0),
      avgWithout: Number(r.avg_without ?? 0),
      gt2With: Number(r.gt2_with ?? 0),
      gt2Without: Number(r.gt2_without ?? 0),
      lt1With: Number(r.lt1_with ?? 0),
    };
  }, null);
}

// ─── timeline (פקיעות + דגל אירוע) ──────────────────────────────────

export type TimelinePoint = { t: number; move: number; event: boolean };

export async function getTimeline(): Promise<TimelinePoint[]> {
  return safe(async () => {
    const rows = await sql<{ d: string; move_pct: number; has_event: boolean }[]>`
      SELECT
        h.expiry_date AS d,
        h.move_pct,
        EXISTS (
          SELECT 1 FROM events e
          WHERE e.event_date BETWEEN h.expiry_date::date - INTERVAL '7 days'
                                 AND h.expiry_date::date
        ) AS has_event
      FROM expiry_history h
      WHERE h.move_pct IS NOT NULL
      ORDER BY h.expiry_date::date
    `;
    if (!rows.length) return [];
    const t0 = new Date(rows[0].d).getTime();
    const t1 = new Date(rows[rows.length - 1].d).getTime();
    const span = Math.max(t1 - t0, 1);
    return rows.map((r) => ({
      t: (new Date(r.d).getTime() - t0) / span,
      move: Number(r.move_pct),
      event: r.has_event,
    }));
  }, []);
}

export async function getTimelineYears(): Promise<number[]> {
  return safe(async () => {
    const [r] = await sql<{ lo: string | null; hi: string | null }[]>`
      SELECT MIN(expiry_date::date)::text AS lo, MAX(expiry_date::date)::text AS hi
      FROM expiry_history
    `;
    if (!r?.lo || !r?.hi) return [];
    const y0 = new Date(r.lo).getFullYear();
    const y1 = new Date(r.hi).getFullYear();
    const step = Math.max(1, Math.round((y1 - y0) / 4));
    const out: number[] = [];
    for (let y = y0; y <= y1; y += step) out.push(y);
    if (out[out.length - 1] !== y1) out.push(y1);
    return out;
  }, []);
}

// ─── פירוט לפי קטגוריה ──────────────────────────────────────────────

export type CatRow = { cat: string; count: number; avg: number; max: number; gt2: number };

export async function getCategoryBreakdown(): Promise<{ rows: CatRow[]; baseline: number }> {
  return safe(async () => {
    const rows = await sql<
      { category: string | null; cnt: number; avg_move: number | null; max_move: number | null; gt2: number | null }[]
    >`
      SELECT
        e.category,
        COUNT(*)                                    AS cnt,
        AVG(h.abs_move_pct)                         AS avg_move,
        MAX(h.abs_move_pct)                         AS max_move,
        100.0 * COUNT(*) FILTER (WHERE h.abs_move_pct > 2) / NULLIF(COUNT(*), 0) AS gt2
      FROM expiry_history h
      JOIN events e
        ON e.event_date BETWEEN h.expiry_date::date - INTERVAL '7 days'
                            AND h.expiry_date::date
      WHERE h.abs_move_pct IS NOT NULL
      GROUP BY e.category
      ORDER BY avg_move DESC
    `;
    const [b] = await sql<{ avg: number | null }[]>`
      SELECT AVG(h.abs_move_pct) AS avg
      FROM expiry_history h
      WHERE h.abs_move_pct IS NOT NULL
        AND NOT EXISTS (
          SELECT 1 FROM events e
          WHERE e.event_date BETWEEN h.expiry_date::date - INTERVAL '7 days'
                                 AND h.expiry_date::date
        )
    `;
    return {
      rows: rows.map((r) => ({
        cat: r.category ?? "אחר",
        count: Number(r.cnt),
        avg: Number(r.avg_move ?? 0),
        max: Number(r.max_move ?? 0),
        gt2: Number(r.gt2 ?? 0),
      })),
      baseline: Number(b?.avg ?? 0),
    };
  }, { rows: [], baseline: 0 });
}

// ─── פקיעות קיצוניות ────────────────────────────────────────────────

export type ExtremeRow = { date: string; type: string; move: number; ev: string };

export async function getExtremes(threshold = 2.5): Promise<{ rows: ExtremeRow[]; explainedPct: number; total: number }> {
  return safe(async () => {
    const rows = await sql<
      { expiry_date: string; expiry_type: string | null; move_pct: number; ev_names: string | null }[]
    >`
      SELECT
        h.expiry_date,
        h.expiry_type,
        h.move_pct,
        (
          SELECT STRING_AGG(e.name, ' · ')
          FROM events e
          WHERE e.event_date BETWEEN h.expiry_date::date - INTERVAL '7 days'
                                 AND h.expiry_date::date
        ) AS ev_names
      FROM expiry_history h
      WHERE h.abs_move_pct >= ${threshold}
      ORDER BY h.abs_move_pct DESC
    `;
    const explained = rows.filter((r) => r.ev_names).length;
    return {
      rows: rows.map((r) => ({
        date: fmtDate(r.expiry_date),
        type: r.expiry_type ?? "",
        move: Number(r.move_pct),
        ev: r.ev_names ?? "",
      })),
      explainedPct: rows.length ? (100 * explained) / rows.length : 0,
      total: rows.length,
    };
  }, { rows: [], explainedPct: 0, total: 0 });
}

// ─── paper trading ──────────────────────────────────────────────────

type TradeLite = {
  portfolio_id: number;
  strategy_name: string | null;
  expiry_date: string | null;
  status: string | null;
  entry_cost: number | null;
  entry_commission: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  closed_at: string | null;
};

export type PortfolioCardData = {
  id: number;
  name: string;
  initial: number;
  current: number;   // מחושב לפי הנוסחה — לא current_balance
  open: number;
  closed: number;
  commission: number;
  strategies: string; // שמות אסטרטגיות ייחודיים מתוך העסקאות
};

function computeBalance(initial: number, trades: TradeLite[]): number {
  let balance = initial;
  for (const t of trades) {
    if (t.status === "open") {
      balance -= Number(t.entry_cost ?? 0) + Number(t.entry_commission ?? 0);
    } else if (t.status === "closed") {
      balance += Number(t.pnl ?? 0);
    }
  }
  return Math.round(balance * 10000) / 10000;
}

export async function getPortfolios(): Promise<PortfolioCardData[]> {
  return safe(async () => {
    const ports = await sql<
      { id: number; name: string; initial_balance: number; commission_per_leg: number | null }[]
    >`
      SELECT id, name, initial_balance, commission_per_leg
      FROM paper_portfolios
      WHERE is_active IS DISTINCT FROM false
      ORDER BY id
    `;
    const trades = await sql<TradeLite[]>`
      SELECT portfolio_id, strategy_name, expiry_date, status,
             entry_cost, entry_commission, pnl, pnl_pct, closed_at
      FROM paper_trades
    `;
    return ports.map((p) => {
      const mine = trades.filter((t) => t.portfolio_id === p.id);
      const names = [...new Set(mine.map((t) => t.strategy_name).filter(Boolean))] as string[];
      return {
        id: Number(p.id),
        name: p.name,
        initial: Number(p.initial_balance),
        current: computeBalance(Number(p.initial_balance), mine),
        open: mine.filter((t) => t.status === "open").length,
        closed: mine.filter((t) => t.status === "closed").length,
        commission: Number(p.commission_per_leg ?? 0),
        strategies: names.length ? names.join(", ") : "—",
      };
    });
  }, []);
}

export type ClosedSummary = {
  closedCount: number; wins: number; losses: number;
  totalPnl: number; avgPnl: number; winRate: number; // winRate ב-[0,1]
};

export async function getClosedSummary(portfolioId?: number): Promise<ClosedSummary> {
  return safe(async () => {
    const rows = portfolioId
      ? await sql<{ pnl: number }[]>`
          SELECT pnl FROM paper_trades
          WHERE status = 'closed' AND pnl IS NOT NULL AND portfolio_id = ${portfolioId}`
      : await sql<{ pnl: number }[]>`
          SELECT pnl FROM paper_trades
          WHERE status = 'closed' AND pnl IS NOT NULL
            AND portfolio_id IN (
              SELECT id FROM paper_portfolios WHERE is_active IS DISTINCT FROM false
            )`;
    const pnls = rows.map((r) => Number(r.pnl));
    const n = pnls.length;
    const wins = pnls.filter((p) => p > 0).length;
    const total = Math.round(pnls.reduce((s, p) => s + p, 0) * 100) / 100;
    return {
      closedCount: n,
      wins,
      losses: pnls.filter((p) => p < 0).length,
      totalPnl: total,
      avgPnl: n ? Math.round((total / n) * 100) / 100 : 0,
      winRate: n ? Math.round((wins / n) * 10000) / 10000 : 0,
    };
  }, { closedCount: 0, wins: 0, losses: 0, totalPnl: 0, avgPnl: 0, winRate: 0 });
}

export type EquityPoint = { label: string; value: number };

// עקומת שווי: אם portfolioId — לתיק; אחרת כוללת (initial = סכום כל התיקים)
export async function getEquityCurve(portfolioId?: number): Promise<{ points: EquityPoint[]; initial: number }> {
  return safe(async () => {
    const ports = portfolioId
      ? await sql<{ initial_balance: number }[]>`
          SELECT initial_balance FROM paper_portfolios WHERE id = ${portfolioId}`
      : await sql<{ initial_balance: number }[]>`
          SELECT initial_balance FROM paper_portfolios WHERE is_active IS DISTINCT FROM false`;
    const initial = ports.reduce((s, p) => s + Number(p.initial_balance), 0);

    const rows = portfolioId
      ? await sql<{ pnl: number; closed_at: string }[]>`
          SELECT pnl, closed_at FROM paper_trades
          WHERE status = 'closed' AND pnl IS NOT NULL AND closed_at IS NOT NULL
            AND portfolio_id = ${portfolioId}
          ORDER BY closed_at`
      : await sql<{ pnl: number; closed_at: string }[]>`
          SELECT pnl, closed_at FROM paper_trades
          WHERE status = 'closed' AND pnl IS NOT NULL AND closed_at IS NOT NULL
            AND portfolio_id IN (
              SELECT id FROM paper_portfolios WHERE is_active IS DISTINCT FROM false
            )
          ORDER BY closed_at`;

    let balance = initial;
    const points = rows.map((r) => {
      balance = Math.round((balance + Number(r.pnl)) * 100) / 100;
      return { label: fmtDate(r.closed_at), value: balance };
    });
    return { points, initial };
  }, { points: [], initial: 0 });
}

export type TrackRowData = {
  name: string; total: number; wins: number; winRate: number; totalPnl: number; avgPnl: number;
};

export async function getTrackRecord(portfolioId?: number): Promise<TrackRowData[]> {
  return safe(async () => {
    const rows = portfolioId
      ? await sql<{ strategy_name: string | null; status: string; pnl: number | null }[]>`
          SELECT strategy_name, status, pnl FROM paper_trades
          WHERE status = 'closed' AND portfolio_id = ${portfolioId}`
      : await sql<{ strategy_name: string | null; status: string; pnl: number | null }[]>`
          SELECT strategy_name, status, pnl FROM paper_trades
          WHERE status = 'closed'
            AND portfolio_id IN (
              SELECT id FROM paper_portfolios WHERE is_active IS DISTINCT FROM false
            )`;
    const groups = new Map<string, number[]>();
    const totals = new Map<string, number>();
    for (const r of rows) {
      const name = r.strategy_name ?? "לא ידוע";
      totals.set(name, (totals.get(name) ?? 0) + 1);
      if (r.pnl !== null) {
        if (!groups.has(name)) groups.set(name, []);
        groups.get(name)!.push(Number(r.pnl));
      }
    }
    const out: TrackRowData[] = [];
    for (const [name, total] of totals) {
      const pnls = groups.get(name) ?? [];
      const n = pnls.length;
      const wins = pnls.filter((p) => p > 0).length;
      const totalPnl = Math.round(pnls.reduce((s, p) => s + p, 0) * 100) / 100;
      out.push({
        name,
        total,
        wins,
        winRate: n ? Math.round((wins / n) * 10000) / 10000 : 0,
        totalPnl,
        avgPnl: n ? Math.round((totalPnl / n) * 100) / 100 : 0,
      });
    }
    return out.sort((a, b) => b.totalPnl - a.totalPnl);
  }, []);
}

// ─── תיק בודד ───────────────────────────────────────────────────────

export type LegData = { action: string; type: string; strike: number; qty: number; pts: number; nis: number };
export type TradeRowData = {
  strat: string; expiry: string; status: string;
  entry: number; comm: number; pnl: number | null; pnlPct: number | null;
  legs: LegData[];
};
export type PortfolioDetail = {
  id: number; name: string; strategies: string;
  initial: number; current: number; commission: number;
  total: number; wins: number; closed: number;
  trades: TradeRowData[];
};

export async function getPortfolioDetail(id: number): Promise<PortfolioDetail | null> {
  return safe(async () => {
    const [p] = await sql<
      { id: number; name: string; initial_balance: number; commission_per_leg: number | null }[]
    >`SELECT id, name, initial_balance, commission_per_leg FROM paper_portfolios WHERE id = ${id}`;
    if (!p) return null;

    const rows = await sql<
      (TradeLite & { legs_json: unknown })[]
    >`
      SELECT portfolio_id, strategy_name, expiry_date, status,
             entry_cost, entry_commission, pnl, pnl_pct, closed_at, legs_json
      FROM paper_trades
      WHERE portfolio_id = ${id}
      ORDER BY opened_at DESC
    `;

    const names = [...new Set(rows.map((t) => t.strategy_name).filter(Boolean))] as string[];
    const closedPnls = rows.filter((t) => t.status === "closed" && t.pnl !== null);

    const parseLegs = (raw: unknown): LegData[] => {
      try {
        const arr = typeof raw === "string" ? JSON.parse(raw) : raw;
        if (!Array.isArray(arr)) return [];
        return arr.map((l: Record<string, unknown>) => ({
          // מיפוי מאומת מול legs_json אמיתי (price_nis, price_pts, action, type, strike, qty)
          action: String(l.action ?? l.side ?? ""),
          type: String(l.type ?? l.option_type ?? ""),
          strike: Number(l.strike ?? 0),
          qty: Number(l.qty ?? l.quantity ?? l.contracts ?? 1),
          pts: Number(l.price_pts ?? l.pts ?? l.price ?? 0),
          nis: Number(l.price_nis ?? l.price_ils ?? l.nis ?? 0),
        }));
      } catch {
        return [];
      }
    };

    return {
      id: Number(p.id),
      name: p.name,
      strategies: names.length ? names.join(", ") : "—",
      initial: Number(p.initial_balance),
      current: computeBalance(Number(p.initial_balance), rows),
      commission: Number(p.commission_per_leg ?? 0),
      total: rows.length,
      wins: closedPnls.filter((t) => Number(t.pnl) > 0).length,
      closed: rows.filter((t) => t.status === "closed").length,
      trades: rows.map((t) => ({
        strat: t.strategy_name ?? "לא ידוע",
        expiry: t.expiry_date ? fmtDate(t.expiry_date) : "—",
        status: t.status ?? "",
        entry: Number(t.entry_cost ?? 0),
        comm: Number(t.entry_commission ?? 0),
        pnl: t.pnl === null ? null : Number(t.pnl),
        pnlPct: t.pnl_pct === null ? null : Number(t.pnl_pct),
        legs: parseLegs(t.legs_json),
      })),
    };
  }, null);
}

// ─── decision engine ────────────────────────────────────────────────

// תאריך+שעה בשעון ישראל: "2026-07-01 13:41:50"
// (decided_at חוזר כ-Date מ-postgres.js, לכן String()+slice היה מחזיר זבל)
const fmtDateTime = (d: string | Date) => {
  const dt = typeof d === "string" ? new Date(d) : d;
  return dt.toLocaleString("sv-SE", { timeZone: "Asia/Jerusalem" }).replace(",", "");
};

export type RankingRow = {
  rank: number; strategy: string;
  condWr: number | null;   // [0,1]
  globalWr: number | null; // [0,1]
  deltaWr: number | null;  // [0,1] signed
  intensity: number | null;
  reason: string;
};

export type CurrentDecision = {
  expiry: string;        // dd/mm/yyyy
  expiryType: string;
  decidedAt: string;
  regime: string;        // raw: calm/normal/volatile/unknown
  riskScore: number | null;
  nSimilar: number | null;
  note: string | null;
  ranking: RankingRow[];
  engineVersion: string | null;
};

export async function getCurrentDecision(): Promise<CurrentDecision | null> {
  return safe(async () => {
    // ההחלטה המתועדת האחרונה לפקיעה הקרובה ביותר שהיא >= היום;
    // אם אין — ההחלטה האחרונה שתועדה בכלל (fallback, מסומן בתאריך).
    let rows = await sql<any[]>`
      SELECT * FROM decision_log
      WHERE expiry_date >= CURRENT_DATE
      ORDER BY expiry_date ASC, decided_at DESC
      LIMIT 1
    `;
    if (!rows.length) {
      rows = await sql<any[]>`
        SELECT * FROM decision_log
        ORDER BY decided_at DESC
        LIMIT 1
      `;
    }
    const row = rows[0];
    if (!row) return null;

    const dj = (typeof row.decision_json === "string"
      ? JSON.parse(row.decision_json)
      : row.decision_json) ?? {};

    const ranking: RankingRow[] = Array.isArray(dj.ranking)
      ? dj.ranking.map((r: any) => ({
          rank: Number(r.rank),
          strategy: String(r.strategy_name ?? r.strategy ?? "—"),
          condWr: r.cond_wr == null ? null : Number(r.cond_wr),
          globalWr: r.global_wr == null ? null : Number(r.global_wr),
          deltaWr: r.delta_wr == null ? null : Number(r.delta_wr),
          intensity: r.cond_intensity == null ? null : Number(r.cond_intensity),
          reason: String(r.reason ?? ""),
        }))
      : [];

    return {
      expiry: fmtDate(row.expiry_date),
      expiryType: row.expiry_type ?? "",
      decidedAt: fmtDate(row.decided_at),
      regime: String(dj.regime?.regime ?? row.regime ?? "unknown"),
      riskScore: row.risk_score == null ? null : Number(row.risk_score),
      nSimilar: row.n_similar == null ? null : Number(row.n_similar),
      note: dj.note ? String(dj.note) : null,
      ranking,
      engineVersion: row.engine_version ?? null,
    };
  }, null);
}

export type DecisionLogRow = {
  when: string; expiry: string; type: string; regime: string;
  topStrategy: string; nSimilar: number | null; risk: number | null;
  trigger: string; version: string;
};

export async function getDecisionLogs(limit = 50): Promise<DecisionLogRow[]> {
  return safe(async () => {
    const rows = await sql<any[]>`
      SELECT decided_at, expiry_date, expiry_type, regime,
             top_strategy_id, n_similar, risk_score, trigger, engine_version,
             decision_json
      FROM decision_log
      ORDER BY decided_at DESC
      LIMIT ${limit}
    `;
    return rows.map((d) => {
      const dj = (typeof d.decision_json === "string"
        ? JSON.parse(d.decision_json)
        : d.decision_json) ?? {};
      // שם האסטרטגיה: מהדירוג ב-json (rank===1) — ה-Streamlit ממפה id→שם מקוד Python,
      // ולנו אין את המפה; הדירוג ב-json מכיל את השם. (תומך strategy_name וגם strategy,
      // בדיוק כמו getCurrentDecision.)
      const topRank = Array.isArray(dj.ranking)
        ? dj.ranking.find((r: any) => Number(r.rank) === 1)
        : null;
      const top =
        (topRank?.strategy_name ?? topRank?.strategy) ||
        (d.top_strategy_id != null ? `אסטרטגיה #${d.top_strategy_id}` : "—");
      return {
        when: fmtDateTime(d.decided_at),
        expiry: fmtDate(d.expiry_date),
        type: d.expiry_type ?? "",
        regime: d.regime ?? "unknown",
        topStrategy: String(top),
        nSimilar: d.n_similar == null ? null : Number(d.n_similar),
        risk: d.risk_score == null ? null : Number(d.risk_score),
        trigger: d.trigger ?? "",
        version: d.engine_version ?? "",
      };
    });
  }, []);
}

// ─── historical analysis ────────────────────────────────────────────

export type YearTypeAgg = {
  year: number;
  type: string;            // ערך expiry_type כפי שבמסד
  count: number;
  ups: number;             // move_pct > 0
  downs: number;           // move_pct < 0
  sumMove: number;         // Σ move_pct
  sumAbs: number;          // Σ abs_move_pct
  maxMove: number;         // MAX move_pct
  minMove: number;         // MIN move_pct
  maxAbs: number;
};

export type HistBin = { type: string; center: number; n: number };

export type HistoricalData = {
  aggs: YearTypeAgg[];
  bins: HistBin[];         // רוחב בין 0.5%, center = אמצע הבין
  medians: { type: string; medianAbs: number }[]; // חציון מוחלט לכל סוג
  medianAllAbs: number;    // חציון מוחלט כולל
};

export async function getHistorical(): Promise<HistoricalData> {
  return safe(async () => {
    const aggs = await sql<any[]>`
      SELECT
        EXTRACT(YEAR FROM expiry_date::date)::int AS year,
        expiry_type                                AS type,
        COUNT(*)::int                              AS count,
        COUNT(*) FILTER (WHERE move_pct > 0)::int  AS ups,
        COUNT(*) FILTER (WHERE move_pct < 0)::int  AS downs,
        COALESCE(SUM(move_pct), 0)                 AS sum_move,
        COALESCE(SUM(abs_move_pct), 0)             AS sum_abs,
        COALESCE(MAX(move_pct), 0)                 AS max_move,
        COALESCE(MIN(move_pct), 0)                 AS min_move,
        COALESCE(MAX(abs_move_pct), 0)             AS max_abs
      FROM expiry_history
      WHERE move_pct IS NOT NULL
      GROUP BY 1, 2
      ORDER BY 1, 2
    `;
    const bins = await sql<any[]>`
      SELECT
        expiry_type                     AS type,
        (FLOOR(move_pct / 0.5) * 0.5 + 0.25) AS center,
        COUNT(*)::int                   AS n
      FROM expiry_history
      WHERE move_pct IS NOT NULL
      GROUP BY 1, 2
      ORDER BY 2
    `;
    // חציונים מסוננים על move_pct IS NOT NULL (כמו df["move_pct"].notna() ב-Streamlit)
    // כדי להתיישר עם aggs/bins ולא לגרור סוגים (למשל 'unknown') ללא move_pct.
    const medians = await sql<any[]>`
      SELECT expiry_type AS type,
             PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY abs_move_pct) AS median_abs
      FROM expiry_history
      WHERE move_pct IS NOT NULL
      GROUP BY 1
    `;
    const [mAll] = await sql<any[]>`
      SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY abs_move_pct) AS m
      FROM expiry_history WHERE move_pct IS NOT NULL
    `;
    return {
      aggs: aggs.map((a) => ({
        year: Number(a.year), type: String(a.type ?? ""),
        count: Number(a.count), ups: Number(a.ups), downs: Number(a.downs),
        sumMove: Number(a.sum_move), sumAbs: Number(a.sum_abs),
        maxMove: Number(a.max_move), minMove: Number(a.min_move), maxAbs: Number(a.max_abs),
      })),
      bins: bins.map((b) => ({ type: String(b.type ?? ""), center: Number(b.center), n: Number(b.n) })),
      medians: medians.map((m) => ({ type: String(m.type ?? ""), medianAbs: Number(m.median_abs) })),
      medianAllAbs: Number(mAll?.m ?? 0),
    };
  }, { aggs: [], bins: [], medians: [], medianAllAbs: 0 });
}

// ─── strategies (moves for client-side backtest) ────────────────────

export type MoveRow = { move: number; type: string; year: number };

export async function getMoves(): Promise<MoveRow[]> {
  return safe(async () => {
    const rows = await sql<{ move_pct: number; expiry_type: string | null; year: number }[]>`
      SELECT move_pct, expiry_type,
             EXTRACT(YEAR FROM expiry_date::date)::int AS year
      FROM expiry_history
      WHERE move_pct IS NOT NULL
      ORDER BY expiry_date::date
    `;
    return rows.map((r) => ({
      move: Number(r.move_pct),
      type: String(r.expiry_type ?? ""),
      year: Number(r.year),
    }));
  }, []);
}

// ─── option chain (upcoming expiry) ─────────────────────────────────

const MULTIPLIER = 50; // ₪ לנקודה
const MIN_STRIKE = 100.0;
const MAX_PRICE_PTS = 500.0;
const ATM_RANGE_PCT = 0.2; // ±20% מ-ATM
const MIN_CHAIN_ROWS = 3;

const numOf = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

// "dd/mm/yyyy HH:MM" בשעון ישראל
const fmtDateTimeShort = (d: string | Date) => {
  const dt = typeof d === "string" ? new Date(d) : d;
  const date = dt.toLocaleDateString("en-GB", {
    timeZone: "Asia/Jerusalem",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  const time = dt.toLocaleTimeString("en-GB", {
    timeZone: "Asia/Jerusalem",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${date} ${time}`;
};

export type ChainRow = {
  strike: number;
  callPts: number; putPts: number;       // נקודות (₪/50)
  callNis: number; putNis: number;       // ₪
  callDelta: number; putDelta: number;   // דצימלי
  callOi: number; putOi: number;
  callVol: number; putVol: number;
};

export type OptionChain = {
  expiry: string;        // dd/mm/yyyy
  expiryIso: string;     // yyyy-mm-dd
  expiryType: string;    // "שבועי" | "חודשי"
  asOf: string;          // dd/mm/yyyy HH:MM (Asia/Jerusalem)
  atmStrike: number | null;
  indexEstimate: number | null;
  atmCallPts: number | null;
  atmPutPts: number | null;
  rows: ChainRow[];
  availableExpiries: string[]; // ISO, בסדר הרלוונטיות
};

export async function getOptionChain(expiryIso?: string): Promise<OptionChain | null> {
  return safe(async () => {
    // פקיעות זמינות (>= היום), ממוינות לפי קרבה
    const exps = await sql<{ iso: string; latest: Date }[]>`
      SELECT expiry_date::date::text AS iso, MAX(fetched_at) AS latest
      FROM tase_putcall
      WHERE expiry_date::date >= CURRENT_DATE
      GROUP BY 1
      ORDER BY iso
    `;
    if (!exps.length) return null;
    const availableExpiries = exps.map((e) => e.iso);
    const targetIso =
      expiryIso && availableExpiries.includes(expiryIso) ? expiryIso : availableExpiries[0];
    const targetMeta = exps.find((e) => e.iso === targetIso)!;

    // שורות הפקיעה — מ-snapshot האחרון בלבד.
    // ה-MAX מחושב בתוך SQL (לא מעבירים Date חזרה — timestamptz הוא מיקרו-שנייה
    // ו-JS Date הוא מילי-שנייה, כך שהשוואת שוויון הייתה מפספסת את כל השורות).
    const raw = await sql<Record<string, unknown>[]>`
      SELECT * FROM tase_putcall
      WHERE expiry_date::date = ${targetIso}::date
        AND fetched_at = (
          SELECT MAX(fetched_at) FROM tase_putcall
          WHERE expiry_date::date = ${targetIso}::date
        )
      ORDER BY expirationprice_call
    `;
    if (!raw.length) return null;

    // מיפוי כל שורות ה-snapshot
    const all: ChainRow[] = raw.map((r) => {
      const callNis = numOf(r.lastrate_call);
      const putNis = numOf(r.lastrate_put);
      return {
        strike: numOf(r.expirationprice_call),
        callPts: callNis / MULTIPLIER,
        putPts: putNis / MULTIPLIER,
        callNis,
        putNis,
        callDelta: numOf(r.delta_call) / 100, // 0-100 → דצימלי
        putDelta: numOf(r.delta_put) / 100,
        callOi: numOf(r.openpositions_call),
        putOi: numOf(r.openpositions_put),
        callVol: numOf(r.overallturnoverunits_call),
        putVol: numOf(r.overallturnoverunits_put),
      };
    });

    // find_atm (1:1 מהמקור): put-call parity → fallback delta≈0.5 → fallback ממוצע סטרייקים.
    // אין שימוש ב-underlingasset.
    let atmStrike: number | null = null;
    let indexEstimate: number | null = null;
    const parity = all.filter((r) => r.callNis > 0 && r.putNis > 0);
    if (parity.length) {
      const a = parity.reduce((x, y) =>
        Math.abs(y.callNis - y.putNis) < Math.abs(x.callNis - x.putNis) ? y : x,
      );
      atmStrike = a.strike;
      indexEstimate = a.strike + (a.callNis - a.putNis) / MULTIPLIER;
    } else if (all.length) {
      const a = all.reduce((x, y) =>
        Math.abs(y.callDelta - 0.5) < Math.abs(x.callDelta - 0.5) ? y : x,
      );
      // אם קיים דלתא שימושי — ATM לפי delta≈0.5; אחרת ממוצע סטרייקים (atmStrike=null)
      if (all.some((r) => r.callDelta > 0)) {
        atmStrike = a.strike;
        indexEstimate = a.strike;
      } else {
        indexEstimate = all.reduce((s, r) => s + r.strike, 0) / all.length;
      }
    }

    // סינון תצוגה סביב ה-ATM: סטרייק תקין, ±20%, והסרת מחירי-קצה
    // (המקור: הסר שורה אם |call|/50 > 500 OR |put|/50 > 500)
    const lo = indexEstimate != null ? indexEstimate * (1 - ATM_RANGE_PCT) : -Infinity;
    const hi = indexEstimate != null ? indexEstimate * (1 + ATM_RANGE_PCT) : Infinity;
    const rows = all.filter(
      (r) =>
        r.strike >= MIN_STRIKE &&
        r.strike >= lo &&
        r.strike <= hi &&
        !(Math.abs(r.callPts) > MAX_PRICE_PTS || Math.abs(r.putPts) > MAX_PRICE_PTS),
    );

    if (rows.length < MIN_CHAIN_ROWS) return null;

    // מחירי ATM מהסטרייק שנבחר
    let atmCallPts: number | null = null;
    let atmPutPts: number | null = null;
    if (atmStrike != null) {
      const atmRow = all.find((r) => r.strike === atmStrike);
      atmCallPts = atmRow ? atmRow.callPts : null;
      atmPutPts = atmRow ? atmRow.putPts : null;
    }

    // סוג הפקיעה מ-decision_log (W/M)
    const [et] = await sql<{ expiry_type: string | null }[]>`
      SELECT expiry_type FROM decision_log
      WHERE expiry_date::date = ${targetIso}::date
      ORDER BY decided_at DESC LIMIT 1
    `;
    const expiryType =
      et?.expiry_type === "M" ? "חודשי" : et?.expiry_type === "W" ? "שבועי" : "";

    return {
      expiry: fmtDate(targetIso),
      expiryIso: targetIso,
      expiryType,
      asOf: fmtDateTimeShort(targetMeta.latest),
      atmStrike,
      indexEstimate,
      atmCallPts,
      atmPutPts,
      rows,
      availableExpiries,
    };
  }, null);
}

// ─── home status ────────────────────────────────────────────────────

export type HomeStatus = {
  expiryCount: number;        // expiry_history עם move_pct
  lastExpiry: string | null;  // MAX(expiry_date) → fmtDate
  chainLoaded: boolean;       // קיימת שרשרת ב-tase_putcall
  chainAsOf: string | null;   // MAX(fetched_at) → fmtDateTime
  eventCount: number;         // events
  lastUpdate: string | null;  // pipeline_state: MAX(updated_at) — אין key ייעודי
                              // כמו last_run; המפתחות מתוארכים (history_copied:DATE וכו')
};

export async function getHomeStatus(): Promise<HomeStatus> {
  return safe(
    async () => {
      const [r] = await sql<
        {
          exp: number;
          lastexp: Date | null;
          chain: boolean;
          chainasof: Date | null;
          ev: number;
          lastupdate: Date | null;
        }[]
      >`
        SELECT
          (SELECT COUNT(*) FROM expiry_history WHERE move_pct IS NOT NULL) AS exp,
          (SELECT MAX(expiry_date::date) FROM expiry_history)              AS lastexp,
          (SELECT EXISTS (SELECT 1 FROM tase_putcall))                     AS chain,
          (SELECT MAX(fetched_at) FROM tase_putcall)                       AS chainasof,
          (SELECT COUNT(*) FROM events)                                    AS ev,
          (SELECT MAX(updated_at) FROM pipeline_state)                     AS lastupdate
      `;
      return {
        expiryCount: Number(r.exp),
        lastExpiry: r.lastexp ? fmtDate(r.lastexp) : null,
        chainLoaded: Boolean(r.chain),
        chainAsOf: r.chainasof ? fmtDateTime(r.chainasof) : null,
        eventCount: Number(r.ev),
        lastUpdate: r.lastupdate ? fmtDateTime(r.lastupdate) : null,
      };
    },
    { expiryCount: 0, lastExpiry: null, chainLoaded: false, chainAsOf: null, eventCount: 0, lastUpdate: null },
  );
}
