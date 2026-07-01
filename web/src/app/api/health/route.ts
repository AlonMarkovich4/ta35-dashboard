import { sql } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const [{ now }] = await sql<{ now: Date }[]>`SELECT NOW() AS now`;

    const rows = await sql<{ table_name: string }[]>`
      SELECT table_name
      FROM information_schema.tables
      WHERE table_schema = 'public'
      ORDER BY table_name
    `;
    const tables = rows.map((r) => r.table_name);

    // Temporary: ?table=NAME also returns that table's columns.
    const table = new URL(request.url).searchParams.get("table");
    const columns = table
      ? await sql<{ column_name: string; data_type: string }[]>`
          SELECT column_name, data_type
          FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = ${table}
          ORDER BY ordinal_position
        `
      : undefined;

    return Response.json({
      ok: true,
      now,
      tableCount: tables.length,
      tables,
      ...(table ? { table, columns } : {}),
    });
  } catch (error) {
    // Log the full error server-side (swallowed errors are dangerous).
    console.error("[/api/health] DB check failed:", error);

    // Surface a useful message even for AggregateError (empty top-level message).
    let message = error instanceof Error ? error.message : String(error);
    const code =
      error && typeof error === "object" && "code" in error
        ? String((error as { code: unknown }).code)
        : undefined;
    if (!message && error instanceof AggregateError) {
      message = error.errors
        .map((e) => (e instanceof Error ? e.message : String(e)))
        .join("; ");
    }

    return Response.json({ ok: false, error: message, code }, { status: 500 });
  }
}
