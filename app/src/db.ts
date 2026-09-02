import * as duckdb from '@duckdb/duckdb-wasm';
import ehWorkerUrl from '@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url';
import ehWasmUrl from '@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url';
import mvpWorkerUrl from '@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url';
import mvpWasmUrl from '@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url';

const ARTIFACTS = ['cells_r10.parquet', 'parcel_cell_xwalk.parquet', 'parcels.parquet'] as const;
const VIEWS: Record<string, string> = {
  'cells_r10.parquet': 'cells',
  'parcel_cell_xwalk.parquet': 'xwalk',
  'parcels.parquet': 'parcels',
};

let conn: duckdb.AsyncDuckDBConnection | null = null;
let initPromise: Promise<void> | null = null;

/**
 * Initialize duckdb-wasm and register the pipeline artifacts as views.
 * Idempotent: React StrictMode double-invokes effects in dev, and without
 * this guard every session paid for two wasm instances + double fetches.
 */
export function initDB(): Promise<void> {
  initPromise ??= doInit();
  return initPromise;
}

async function doInit(): Promise<void> {
  const bundle = await duckdb.selectBundle({
    mvp: { mainModule: mvpWasmUrl, mainWorker: mvpWorkerUrl },
    eh: { mainModule: ehWasmUrl, mainWorker: ehWorkerUrl },
  });
  const worker = new Worker(bundle.mainWorker!);
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  conn = await db.connect();

  for (const name of ARTIFACTS) {
    const url = new URL(`/${name}`, window.location.origin).href;
    const head = await fetch(url, { method: 'HEAD' });
    if (!head.ok) {
      throw new Error(
        `artifact missing: ${name} (HTTP ${head.status}).\n` +
          `Expected the pipeline outputs in data/processed/54081/ — run the ` +
          `pipeline's validate stage, then restart the dev server.`,
      );
    }
    await db.registerFileURL(name, url, duckdb.DuckDBDataProtocol.HTTP, false);
    await conn.query(`CREATE VIEW ${VIEWS[name]} AS SELECT * FROM read_parquet('${name}')`);
  }

  for (const name of ['parcels.geojson', 'county_boundary.geojson']) {
    const head = await fetch(`/${name}`, { method: 'HEAD' });
    if (!head.ok) {
      throw new Error(
        `artifact missing: ${name} (HTTP ${head.status}).\n` +
          `Expected the pipeline outputs in data/processed/54081/ — run the ` +
          `pipeline's validate stage, then restart the dev server.`,
      );
    }
  }

  // Fail at startup, not at first slider drag, if the registry and the
  // artifact schema have drifted apart.
  const cols = await query(`SELECT column_name FROM information_schema.columns WHERE table_name = 'cells'`);
  const present = new Set(cols.map((r) => String(r.column_name)));
  const { loadRegistry } = await import('./registry');
  const reg = loadRegistry();
  const wanted = [...reg.criteria.map((c) => c.column), ...reg.masks.map((m) => m.column)];
  const missing = wanted.filter((c) => !present.has(c));
  if (missing.length) {
    throw new Error(
      `cells_r10.parquet is missing column(s) the registry expects: ${missing.join(', ')}.\n` +
        `criteria.json and the published artifacts are out of sync — re-run the pipeline.`,
    );
  }
}

/** Run SQL, return plain JS row objects. */
export async function query(sql: string): Promise<Record<string, unknown>[]> {
  if (!conn) throw new Error('db not initialized');
  const result = await conn.query(sql);
  return result.toArray().map((row) => row.toJSON());
}
