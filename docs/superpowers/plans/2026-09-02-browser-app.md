# Browser Scoring App Implementation Plan (Plan 2 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local-first browser app (layout A: weight sliders left, deck.gl map center, ranked parcel table bottom) that re-scores 118,972 hex cells and 60,683 Raleigh County parcels on every slider change via DuckDB-WASM, with CSV + GeoJSON export.

**Architecture:** Vite + React + TypeScript SPA in `app/`. DuckDB-WASM loads the four published artifacts over HTTP from the Vite server (`publicDir` pointed at `data/processed/54081/`). One generated SQL statement per re-score: membership expressions → weighted aggregation → multiplicative masks → crosswalk join → overlap-weighted parcel means. deck.gl renders cell scores (`H3HexagonLayer`) or parcel choropleth (`GeoJsonLayer`). No backend, no basemap tiles (post-MVP).

**Tech Stack:** react 18, vite 6, typescript 5, @duckdb/duckdb-wasm (browser), deck.gl 9 (core/react/layers/geo-layers), h3-js (cell centers for view fitting), vitest + @duckdb/node-api (golden tests run the generated SQL against real DuckDB in Node).

**Ground truth this plan is written against (verified 2026-09-01):**
- `cells_r10.parquet` — 118,972 rows × 14 cols: `h3_index` (string), `h3_r9`, `h3_r8`, `in_county` (bool), `slope_mean_pct`, `slope_pct_gt15`, `flood_pct_a_ae`, `floodway_pct`, `water_in_service` (int8 0/1), `water_conf` (string: `none` | `authoritative` | `modeled:<method>`), `road_dist_m`, `transmission_dist_m`, `mined_pct`, `nlcd_mode` (int16, nullable-typed but 0 nulls).
- `parcel_cell_xwalk.parquet` — `parcel_id`, `h3_index`, `overlap_frac` ∈ (0,1]; per-parcel sums ≈ 1.
- `parcels.parquet` — `parcel_id`, `acres` (canonical), `FullOwnerName`, `DeededAcres`, `CalculatedAcres`, `DistrictName`, `TaxDistrict`, `FullPhysicalAddress`, `PropertyClassDescription`, `Acres_C`.
- `parcels.geojson` — 60,683 features, properties: `parcel_id` only, EPSG:4326, 2D, 6-decimal coords, 19 MB.
- `config/criteria.json` — 6 criteria + 3 masks + `notes` block. **Contract reminders from its notes:** `nlcd_mode` must be `CAST(... AS VARCHAR)` for the lookup and the CASE needs `ELSE miss_score`; `water_conf` badge = value starts with `modeled:`; slope membership is calibrated (midpoint 20, spread 3; slope_limit default threshold 40).

**Reference:** spec `docs/superpowers/specs/2026-09-01-suitability-mvp-design.md`. Commands run from repo root (`hexbin`) in Git Bash. All commands FOREGROUND with explicit timeouts.

---

## File structure

```
app/
  package.json  tsconfig.json  vite.config.ts  index.html
  src/
    main.tsx            # React root
    App.tsx             # layout shell, state owner, load/error screens
    styles.css          # dark flex layout, one file
    types.ts            # Registry + ScoringConfig types
    registry.ts         # load/validate criteria.json, default config
    scoring.ts          # THE CORE: config -> SQL (cell, parcel, hex-agg)
    db.ts               # duckdb-wasm init, artifact registration, query helper
    exports.ts          # CSV + GeoJSON download builders
    components/
      WeightPanel.tsx   # sliders, masks, threshold, WLC/geometric, res, mode
      MapView.tsx       # deck.gl layers + tooltip
      RankTable.tsx     # top-500 table, row click -> zoom, export buttons
  tests/
    scoring.test.ts     # golden tests: generated SQL vs hand-computed, via @duckdb/node-api
    registry.test.ts    # registry validation + defaults
```

Scope choices locked here: table renders the **top 500** parcels (exports include all 60,683); hex layers render `in_county` cells only; no basemap; no saved scenarios.

---

### Task 1: App scaffold

**Files:**
- Create: `app/package.json`, `app/tsconfig.json`, `app/vite.config.ts`, `app/index.html`, `app/src/main.tsx`, `app/src/App.tsx`, `app/src/styles.css`
- Modify: `.gitignore`

- [ ] **Step 1: Write `app/package.json`**

```json
{
  "name": "hexbin-app",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "@deck.gl/core": "^9.0.0",
    "@deck.gl/geo-layers": "^9.0.0",
    "@deck.gl/layers": "^9.0.0",
    "@deck.gl/react": "^9.0.0",
    "@duckdb/duckdb-wasm": "^1.29.0",
    "h3-js": "^4.1.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@duckdb/node-api": "^1.2.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.6.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2: Write `app/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true
  },
  "include": ["src", "tests"]
}
```

- [ ] **Step 3: Write `app/vite.config.ts`**

```ts
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  // Serve the published pipeline artifacts at / — no copying, no backend.
  // MVP is single-county by spec; multi-county needs a served index instead.
  publicDir: '../data/processed/54081',
});
```

- [ ] **Step 4: Write `app/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>WV Parcel Suitability — Raleigh County</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Write `app/src/main.tsx`, placeholder `app/src/App.tsx`, and `app/src/styles.css`**

```tsx
// main.tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

```tsx
// App.tsx (placeholder — replaced in Task 7)
export default function App() {
  return <div className="loading">WV Parcel Suitability — scaffold OK</div>;
}
```

```css
/* styles.css */
* { box-sizing: border-box; margin: 0; }
html, body, #root { height: 100%; }
body { font: 13px/1.45 system-ui, sans-serif; background: #16181d; color: #d9dce1; }
.loading, .error-screen { display: flex; align-items: center; justify-content: center; height: 100%; padding: 2rem; text-align: center; white-space: pre-wrap; }
.error-screen { color: #ff7b72; }
.app { display: flex; flex-direction: column; height: 100%; }
.app-main { display: flex; flex: 1; min-height: 0; }
.panel { width: 300px; overflow-y: auto; padding: 12px; background: #1c1f26; border-right: 1px solid #2a2e37; }
.map-wrap { flex: 1; position: relative; }
.rank-dock { height: 34%; min-height: 180px; overflow: auto; background: #1c1f26; border-top: 1px solid #2a2e37; }
.rank-dock table { width: 100%; border-collapse: collapse; }
.rank-dock th, .rank-dock td { padding: 3px 8px; text-align: right; white-space: nowrap; }
.rank-dock th { position: sticky; top: 0; background: #232733; cursor: default; }
.rank-dock td:nth-child(2), .rank-dock th:nth-child(2) { text-align: left; }
.rank-dock tr:hover td { background: #262b36; }
.slider-row { margin: 8px 0; }
.slider-row label { display: flex; justify-content: space-between; }
.badge { font-size: 10px; padding: 0 4px; border-radius: 3px; background: #7d5900; color: #ffd57a; margin-left: 6px; }
.group-title { margin: 14px 0 4px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #8a919e; }
.controls-row { display: flex; gap: 8px; align-items: center; margin: 6px 0; flex-wrap: wrap; }
button { background: #2d6cdf; color: white; border: 0; border-radius: 4px; padding: 4px 10px; cursor: pointer; }
button.secondary { background: #3a4150; }
.masked-flag { color: #ff7b72; }
```

- [ ] **Step 6: Append `node_modules/` and `app/dist/` to `.gitignore`, install, and smoke the dev server**

```bash
printf 'node_modules/\napp/dist/\n' >> .gitignore
cd app && npm install
```
(timeout 600000 — first install is heavy)

```bash
cd app && npx vite build 2>&1 | tail -5
```
Expected: build completes without error. Then verify artifact serving wiring by checking the publicDir resolves:
```bash
ls app/../data/processed/54081/cells_r10.parquet
```

- [ ] **Step 7: Commit**

```bash
git add .gitignore app/package.json app/package-lock.json app/tsconfig.json app/vite.config.ts app/index.html app/src
git commit -m "feat: app scaffold (vite + react + ts, artifacts served from publicDir)"
```

---

### Task 2: Registry types + config model (TDD)

**Files:**
- Create: `app/src/types.ts`, `app/src/registry.ts`
- Test: `app/tests/registry.test.ts`

- [ ] **Step 1: Write `app/src/types.ts`**

```ts
export type MembershipFn =
  | { fn: 'small'; midpoint: number; spread: number }
  | { fn: 'binary' }
  | { fn: 'lookup'; miss_score: number; table: Record<string, number> };

export interface Criterion {
  key: string;
  label: string;
  column: string;
  group: string;
  membership: MembershipFn;
  weight: number;
  confidence: string;
  confidence_column?: string;
}

export interface Mask {
  key: string;
  label: string;
  column: string;
  predicate: string; // "> 0" or "> {threshold}"
  default_threshold?: number;
}

export interface Registry {
  criteria: Criterion[];
  masks: Mask[];
}

export interface ScoringConfig {
  weights: Record<string, number>;        // criterion key -> raw weight (unnormalized)
  masksEnabled: Record<string, boolean>;  // mask key -> on/off
  slopeThreshold: number;                 // fills {threshold}
  aggregation: 'wlc' | 'geometric';
  resolution: 8 | 9 | 10;
  displayMode: 'hex' | 'parcel';
}
```

- [ ] **Step 2: Write failing tests `app/tests/registry.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import { defaultConfig, loadRegistry } from '../src/registry';

describe('registry', () => {
  it('loads criteria.json with 6 criteria, 3 masks, weights summing to 1', () => {
    const reg = loadRegistry();
    expect(reg.criteria).toHaveLength(6);
    expect(reg.masks).toHaveLength(3);
    const sum = reg.criteria.reduce((s, c) => s + c.weight, 0);
    expect(sum).toBeCloseTo(1.0, 6);
  });

  it('rejects a registry with a lookup missing miss_score', () => {
    expect(() =>
      loadRegistry({
        criteria: [{ key: 'x', label: 'x', column: 'c', group: 'g', weight: 1,
          confidence: 'authoritative', membership: { fn: 'lookup', table: {} } as never }],
        masks: [],
      }),
    ).toThrow(/miss_score/);
  });

  it('builds defaults from the registry', () => {
    const cfg = defaultConfig(loadRegistry());
    expect(cfg.weights['slope']).toBeCloseTo(0.2);
    expect(cfg.masksEnabled['floodway']).toBe(true);
    expect(cfg.slopeThreshold).toBe(40);
    expect(cfg.aggregation).toBe('wlc');
    expect(cfg.resolution).toBe(8);
    expect(cfg.displayMode).toBe('hex');
  });
});
```

- [ ] **Step 3: Run to verify failure**

```bash
cd app && npx vitest run tests/registry.test.ts
```
Expected: FAIL — cannot resolve `../src/registry`.

- [ ] **Step 4: Write `app/src/registry.ts`**

```ts
import registryJson from '../../config/criteria.json';
import type { Registry, ScoringConfig } from './types';

/** Validate + return the criteria registry. Pass an override for tests. */
export function loadRegistry(raw?: unknown): Registry {
  const reg = (raw ?? registryJson) as Registry;
  if (!Array.isArray(reg.criteria) || reg.criteria.length === 0) {
    throw new Error('criteria.json: no criteria defined');
  }
  for (const c of reg.criteria) {
    if (!c.key || !c.column || !c.membership) {
      throw new Error(`criteria.json: criterion ${JSON.stringify(c.key)} is incomplete`);
    }
    if (c.membership.fn === 'lookup' && typeof c.membership.miss_score !== 'number') {
      throw new Error(`criteria.json: lookup criterion '${c.key}' needs miss_score — ` +
        `an unmatched class must score, not go NULL`);
    }
  }
  return reg;
}

export function defaultConfig(reg: Registry): ScoringConfig {
  const slopeLimit = reg.masks.find((m) => m.key === 'slope_limit');
  return {
    weights: Object.fromEntries(reg.criteria.map((c) => [c.key, c.weight])),
    masksEnabled: Object.fromEntries(reg.masks.map((m) => [m.key, true])),
    slopeThreshold: slopeLimit?.default_threshold ?? 40,
    aggregation: 'wlc',
    resolution: 8,
    displayMode: 'hex',
  };
}
```

- [ ] **Step 5: Run tests to verify pass, commit**

```bash
cd app && npx vitest run tests/registry.test.ts
```
Expected: 3 passed.

```bash
git add app/src/types.ts app/src/registry.ts app/tests/registry.test.ts
git commit -m "feat: registry loader, validation, and default scoring config"
```

---

### Task 3: SQL generation (TDD golden tests — the heart of the app)

**Files:**
- Create: `app/src/scoring.ts`
- Test: `app/tests/scoring.test.ts`

The golden test creates the three tables in an in-memory **real DuckDB** (via `@duckdb/node-api`), runs the exact SQL the browser will run, and compares against hand-computed numbers. This one test protects the entire scoring semantics.

- [ ] **Step 1: Write failing tests `app/tests/scoring.test.ts`**

```ts
import { DuckDBInstance } from '@duckdb/node-api';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { loadRegistry, defaultConfig } from '../src/registry';
import { buildCellScoreSQL, buildHexAggSQL, buildParcelScoreSQL, membershipSQL } from '../src/scoring';
import type { ScoringConfig } from '../src/types';

const reg = loadRegistry();

// Fixture: 3 cells, 2 parcels. Hand-computed below with the calibrated registry
// (slope small(20,3), flood small(15,3), water binary, roads small(1500,3),
// transmission small(3000,3), landcover lookup, default weights .2/.15/.2/.15/.15/.15).
//
// cell A: slope 20 (m=0.5), flood 0 (m=1), water 1 (m=1), road 1500 (m=0.5),
//         transmission 3000 (m=0.5), nlcd 23 (m=1.0); no masks trip.
//         WLC = .2*.5 + .15*1 + .2*1 + .15*.5 + .15*.5 + .15*1 = 0.75
// cell B: same measurements but floodway_pct = 10 -> mask factor 0 -> score 0
// cell C: slope 60 -> trips slope_limit (>40) -> score 0; also nlcd 999
//         (unlisted class -> miss_score 0.5 must be used, NOT NULL)
// parcel P1 = 100% cell A                      -> score 0.75
// parcel P2 = 50% cell A + 50% cell B          -> score 0.375
const FIXTURE = `
CREATE TABLE cells AS SELECT * FROM (VALUES
  ('a', 'a9', 'a8', true,  20.0, 0.0, 0.0,  0.0, 1::TINYINT, 'authoritative', 1500.0, 3000.0, 0.0, 23::SMALLINT),
  ('b', 'b9', 'b8', true,  20.0, 0.0, 0.0, 10.0, 1::TINYINT, 'authoritative', 1500.0, 3000.0, 0.0, 23::SMALLINT),
  ('c', 'c9', 'c8', false, 60.0, 0.0, 0.0,  0.0, 1::TINYINT, 'none',          1500.0, 3000.0, 0.0, 999::SMALLINT)
) t(h3_index, h3_r9, h3_r8, in_county, slope_mean_pct, slope_pct_gt15, flood_pct_a_ae,
    floodway_pct, water_in_service, water_conf, road_dist_m, transmission_dist_m, mined_pct, nlcd_mode);
CREATE TABLE xwalk AS SELECT * FROM (VALUES
  ('P1', 'a', 1.0), ('P2', 'a', 0.5), ('P2', 'b', 0.5)
) t(parcel_id, h3_index, overlap_frac);
CREATE TABLE parcels AS SELECT * FROM (VALUES
  ('P1', 12.5, 'OWNER ONE'), ('P2', 40.0, 'OWNER TWO')
) t(parcel_id, acres, FullOwnerName);
`;

let db: Awaited<ReturnType<typeof DuckDBInstance.create>>;
let conn: Awaited<ReturnType<typeof db.connect>>;

beforeAll(async () => {
  db = await DuckDBInstance.create(':memory:');
  conn = await db.connect();
  await conn.run(FIXTURE);
});
afterAll(() => conn.closeSync());

async function rows(sql: string): Promise<Record<string, unknown>[]> {
  const reader = await conn.runAndReadAll(sql);
  return reader.getRowObjects() as Record<string, unknown>[];
}

const cfg: ScoringConfig = defaultConfig(reg);

describe('membershipSQL', () => {
  it('small: 0.5 at the midpoint, 1 at zero', async () => {
    const expr = membershipSQL({ fn: 'small', midpoint: 20, spread: 3 }, 'slope_mean_pct');
    const r = await rows(`SELECT h3_index, ${expr} AS m FROM cells ORDER BY h3_index`);
    expect(Number(r[0].m)).toBeCloseTo(0.5, 6);      // slope 20 at midpoint 20
  });
  it('lookup: unmatched class takes miss_score, never NULL', async () => {
    const lc = reg.criteria.find((c) => c.key === 'landcover')!;
    const expr = membershipSQL(lc.membership, lc.column);
    const r = await rows(`SELECT h3_index, ${expr} AS m FROM cells WHERE h3_index = 'c'`);
    expect(Number(r[0].m)).toBeCloseTo(0.5, 6);      // nlcd 999 -> miss_score
  });
});

describe('cell scores (WLC + masks)', () => {
  it('hand-computed scores match', async () => {
    const r = await rows(`${buildCellScoreSQL(reg, cfg)} ORDER BY h3_index`);
    expect(Number(r[0].score)).toBeCloseTo(0.75, 6);  // cell a
    expect(Number(r[1].score)).toBeCloseTo(0.0, 6);   // cell b: floodway masked
    expect(Number(r[2].score)).toBeCloseTo(0.0, 6);   // cell c: slope_limit masked
  });
  it('disabling the floodway mask restores cell b', async () => {
    const noFloodway = { ...cfg, masksEnabled: { ...cfg.masksEnabled, floodway: false } };
    const r = await rows(`${buildCellScoreSQL(reg, noFloodway)} ORDER BY h3_index`);
    expect(Number(r[1].score)).toBeCloseTo(0.75, 6);
  });
  it('weights are normalized: doubling every weight changes nothing', async () => {
    const doubled = { ...cfg, weights: Object.fromEntries(
      Object.entries(cfg.weights).map(([k, v]) => [k, v * 2])) };
    const r = await rows(`${buildCellScoreSQL(reg, doubled)} ORDER BY h3_index`);
    expect(Number(r[0].score)).toBeCloseTo(0.75, 6);
  });
});

describe('parcel scores', () => {
  it('overlap-weighted means match hand computation', async () => {
    const r = await rows(`${buildParcelScoreSQL(reg, cfg)} ORDER BY parcel_id`);
    expect(Number(r[0].score)).toBeCloseTo(0.75, 6);   // P1
    expect(Number(r[1].score)).toBeCloseTo(0.375, 6);  // P2: half its area masked
    expect(Number(r[1].masked_frac)).toBeCloseTo(0.5, 6);
    expect(r[0].FullOwnerName).toBe('OWNER ONE');
  });
});

describe('hex aggregation', () => {
  it('res-8 view averages in_county cells only', async () => {
    const r = await rows(buildHexAggSQL(reg, { ...cfg, resolution: 8 }));
    // cells a and b are in_county (different r8 parents); c is fringe -> excluded
    expect(r).toHaveLength(2);
  });
  it('res 10 passes cells through', async () => {
    const r = await rows(buildHexAggSQL(reg, { ...cfg, resolution: 10 }));
    expect(r).toHaveLength(2); // a, b (c excluded: fringe)
  });
});

describe('geometric aggregation', () => {
  it('geometric mean of the same memberships is below WLC and nonzero', async () => {
    const geo = { ...cfg, aggregation: 'geometric' as const };
    const r = await rows(`${buildCellScoreSQL(reg, geo)} ORDER BY h3_index`);
    const a = Number(r[0].score);
    // hand: exp(.2*ln(.5)+.15*ln(1)+.2*ln(1)+.15*ln(.5)+.15*ln(.5)+.15*ln(1))
    //     = exp(0.5*ln(0.5)) = 0.7071
    expect(a).toBeCloseTo(Math.SQRT1_2, 4);
    expect(a).toBeLessThan(0.75);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd app && npx vitest run tests/scoring.test.ts
```
Expected: FAIL — cannot resolve `../src/scoring`.

- [ ] **Step 3: Write `app/src/scoring.ts`**

```ts
import type { MembershipFn, Registry, ScoringConfig } from './types';

/** SQL expression producing the 0-1 membership value for one criterion. */
export function membershipSQL(m: MembershipFn, column: string): string {
  switch (m.fn) {
    case 'small':
      // ESRI FuzzySmall: 1/(1+(x/midpoint)^spread) — 1 at 0, 0.5 at midpoint
      return `(1.0 / (1.0 + POW(GREATEST(${column}, 0) / ${m.midpoint}, ${m.spread})))`;
    case 'binary':
      return `(CAST(${column} AS DOUBLE))`;
    case 'lookup': {
      // nlcd_mode is int16; keys are JSON strings -> cast. ELSE is mandatory:
      // an unmatched class returning NULL would poison the whole weighted sum.
      const whens = Object.entries(m.table)
        .map(([k, v]) => `WHEN '${k}' THEN ${v}`)
        .join(' ');
      return `(CASE CAST(${column} AS VARCHAR) ${whens} ELSE ${m.miss_score} END)`;
    }
  }
}

function maskFactorSQL(reg: Registry, cfg: ScoringConfig): string {
  const parts = reg.masks
    .filter((mk) => cfg.masksEnabled[mk.key])
    .map((mk) => {
      const pred = mk.predicate.replace('{threshold}', String(cfg.slopeThreshold));
      return `(CASE WHEN ${mk.column} ${pred} THEN 0.0 ELSE 1.0 END)`;
    });
  return parts.length ? parts.join(' * ') : '1.0';
}

function normalizedWeights(reg: Registry, cfg: ScoringConfig): Map<string, number> {
  const total = reg.criteria.reduce((s, c) => s + (cfg.weights[c.key] ?? 0), 0);
  if (total <= 0) throw new Error('all weights are zero — scoring is undefined');
  return new Map(reg.criteria.map((c) => [c.key, (cfg.weights[c.key] ?? 0) / total]));
}

/**
 * Cell scores: one row per cell with per-criterion memberships (m_<key>),
 * mask_factor, and the aggregate score. Table `cells` must be registered.
 */
export function buildCellScoreSQL(reg: Registry, cfg: ScoringConfig): string {
  const w = normalizedWeights(reg, cfg);
  const memberCols = reg.criteria
    .map((c) => `${membershipSQL(c.membership, c.column)} AS m_${c.key}`)
    .join(',\n    ');
  const agg =
    cfg.aggregation === 'wlc'
      ? reg.criteria.map((c) => `${w.get(c.key)} * m_${c.key}`).join(' + ')
      : `EXP(${reg.criteria
          .map((c) => `${w.get(c.key)} * LN(GREATEST(m_${c.key}, 0.000001))`)
          .join(' + ')})`;
  return `
SELECT *, (${agg}) * mask_factor AS score
FROM (
  SELECT h3_index, h3_r9, h3_r8, in_county,
    ${memberCols},
    ${maskFactorSQL(reg, cfg)} AS mask_factor
  FROM cells
)`;
}

/** Parcel scores: overlap-weighted mean of cell scores + memberships, joined to attributes. */
export function buildParcelScoreSQL(reg: Registry, cfg: ScoringConfig): string {
  const memberAvgs = reg.criteria
    .map((c) => `SUM(s.m_${c.key} * x.overlap_frac) / SUM(x.overlap_frac) AS m_${c.key}`)
    .join(',\n    ');
  return `
WITH scored AS (${buildCellScoreSQL(reg, cfg)})
SELECT p.*, agg.score, agg.masked_frac, ${reg.criteria.map((c) => `agg.m_${c.key}`).join(', ')}
FROM (
  SELECT x.parcel_id,
    SUM(s.score * x.overlap_frac) / SUM(x.overlap_frac) AS score,
    SUM((1.0 - s.mask_factor) * x.overlap_frac) / SUM(x.overlap_frac) AS masked_frac,
    ${memberAvgs}
  FROM xwalk x JOIN scored s USING (h3_index)
  GROUP BY x.parcel_id
) agg
JOIN parcels p USING (parcel_id)
ORDER BY agg.score DESC`;
}

/** Hex display data at the configured resolution — in_county cells only. */
export function buildHexAggSQL(reg: Registry, cfg: ScoringConfig): string {
  const memberAvgs = reg.criteria.map((c) => `AVG(m_${c.key}) AS m_${c.key}`).join(', ');
  const scored = buildCellScoreSQL(reg, cfg);
  if (cfg.resolution === 10) {
    return `SELECT h3_index AS h3, score, mask_factor, ${reg.criteria
      .map((c) => `m_${c.key}`)
      .join(', ')} FROM (${scored}) WHERE in_county`;
  }
  const parent = cfg.resolution === 9 ? 'h3_r9' : 'h3_r8';
  return `
SELECT ${parent} AS h3, AVG(score) AS score, MIN(mask_factor) AS mask_factor, ${memberAvgs}
FROM (${scored}) WHERE in_county GROUP BY ${parent}`;
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd app && npx vitest run
```
Expected: registry (3) + scoring (9) = 12 passed. If any golden number mismatches, re-derive the hand computation before touching the SQL — the test values in Step 1 are the contract.

- [ ] **Step 5: Commit**

```bash
git add app/src/scoring.ts app/tests/scoring.test.ts
git commit -m "feat: SQL generation for cell/parcel/hex scoring with golden tests"
```

---

### Task 4: DuckDB-WASM init + query layer

**Files:**
- Create: `app/src/db.ts`

No unit tests (browser-runtime code); verified by the Task 7 live smoke.

- [ ] **Step 1: Write `app/src/db.ts`**

```ts
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

/** Initialize duckdb-wasm and register the pipeline artifacts as views. */
export async function initDB(): Promise<void> {
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
```

- [ ] **Step 2: Type-check and commit**

```bash
cd app && npx tsc -b
git add app/src/db.ts
git commit -m "feat: duckdb-wasm init, artifact views, startup schema check"
```

---

### Task 5: WeightPanel component

**Files:**
- Create: `app/src/components/WeightPanel.tsx`

- [ ] **Step 1: Write `app/src/components/WeightPanel.tsx`**

```tsx
import type { Registry, ScoringConfig } from '../types';

interface Props {
  registry: Registry;
  config: ScoringConfig;
  onChange: (cfg: ScoringConfig) => void;
}

export default function WeightPanel({ registry, config, onChange }: Props) {
  const groups = [...new Set(registry.criteria.map((c) => c.group))];
  const total = Object.values(config.weights).reduce((s, w) => s + w, 0);

  return (
    <div className="panel">
      {groups.map((g) => (
        <div key={g}>
          <div className="group-title">{g}</div>
          {registry.criteria.filter((c) => c.group === g).map((c) => (
            <div className="slider-row" key={c.key}>
              <label>
                <span>
                  {c.label}
                  {c.confidence !== 'authoritative' && <span className="badge">{c.confidence}</span>}
                </span>
                <span>{total > 0 ? ((config.weights[c.key] / total) * 100).toFixed(0) : '—'}%</span>
              </label>
              <input
                type="range" min={0} max={100} step={1}
                value={Math.round(config.weights[c.key] * 100)}
                onChange={(e) =>
                  onChange({ ...config, weights: { ...config.weights, [c.key]: Number(e.target.value) / 100 } })}
                style={{ width: '100%' }}
              />
            </div>
          ))}
        </div>
      ))}

      <div className="group-title">Constraints (hard masks)</div>
      {registry.masks.map((m) => (
        <div className="controls-row" key={m.key}>
          <label>
            <input
              type="checkbox"
              checked={config.masksEnabled[m.key]}
              onChange={(e) =>
                onChange({ ...config, masksEnabled: { ...config.masksEnabled, [m.key]: e.target.checked } })}
            />{' '}
            {m.label}
          </label>
          {m.key === 'slope_limit' && (
            <input
              type="number" min={5} max={100} step={5}
              value={config.slopeThreshold}
              onChange={(e) => onChange({ ...config, slopeThreshold: Number(e.target.value) })}
              style={{ width: 55 }}
            />
          )}
        </div>
      ))}

      <div className="group-title">Scoring</div>
      <div className="controls-row">
        <label><input type="radio" checked={config.aggregation === 'wlc'}
          onChange={() => onChange({ ...config, aggregation: 'wlc' })} /> Weighted sum</label>
        <label><input type="radio" checked={config.aggregation === 'geometric'}
          onChange={() => onChange({ ...config, aggregation: 'geometric' })} /> Geometric</label>
      </div>

      <div className="group-title">Display</div>
      <div className="controls-row">
        <label>Hex res{' '}
          <select value={config.resolution}
            onChange={(e) => onChange({ ...config, resolution: Number(e.target.value) as 8 | 9 | 10 })}>
            <option value={8}>8 (coarse)</option>
            <option value={9}>9</option>
            <option value={10}>10 (full)</option>
          </select>
        </label>
        <label><input type="radio" checked={config.displayMode === 'hex'}
          onChange={() => onChange({ ...config, displayMode: 'hex' })} /> Hexes</label>
        <label><input type="radio" checked={config.displayMode === 'parcel'}
          onChange={() => onChange({ ...config, displayMode: 'parcel' })} /> Parcels</label>
      </div>
      {total === 0 && <p className="masked-flag">All weights are zero — scoring disabled.</p>}
    </div>
  );
}
```

- [ ] **Step 2: Type-check and commit**

```bash
cd app && npx tsc -b
git add app/src/components/WeightPanel.tsx
git commit -m "feat: WeightPanel — sliders, masks, aggregation, display controls"
```

---

### Task 6: MapView + RankTable + exports

**Files:**
- Create: `app/src/components/MapView.tsx`, `app/src/components/RankTable.tsx`, `app/src/exports.ts`

- [ ] **Step 1: Write `app/src/exports.ts`**

```ts
import type { Registry } from './types';

function download(filename: string, mime: string, content: string): void {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

const csvCell = (v: unknown): string => {
  if (v == null) return '';
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** Full ranked parcel list -> CSV download. */
export function exportCSV(rows: Record<string, unknown>[], reg: Registry): void {
  const cols = ['parcel_id', 'score', 'masked_frac', 'acres', 'FullOwnerName',
    'DistrictName', 'PropertyClassDescription', ...reg.criteria.map((c) => `m_${c.key}`)];
  const lines = [
    'rank,' + cols.join(','),
    ...rows.map((r, i) => `${i + 1},` + cols.map((c) => csvCell(r[c])).join(',')),
  ];
  download('parcel_scores_54081.csv', 'text/csv', lines.join('\n'));
}

/** Scores merged onto the display geometry -> GeoJSON download. */
export function exportGeoJSON(
  rows: Record<string, unknown>[],
  parcelsGeojson: { type: string; features: { properties: { parcel_id: string } }[] },
): void {
  const byId = new Map(rows.map((r, i) => [String(r.parcel_id), { ...r, rank: i + 1 }]));
  const features = parcelsGeojson.features
    .filter((f) => byId.has(f.properties.parcel_id))
    .map((f) => ({ ...f, properties: { ...f.properties, ...byId.get(f.properties.parcel_id) } }));
  download('parcel_scores_54081.geojson', 'application/geo+json',
    JSON.stringify({ type: 'FeatureCollection', features }));
}
```

- [ ] **Step 2: Write `app/src/components/MapView.tsx`**

```tsx
import { GeoJsonLayer } from '@deck.gl/layers';
import { H3HexagonLayer } from '@deck.gl/geo-layers';
import DeckGL from '@deck.gl/react';
import type { Registry, ScoringConfig } from '../types';

// Viridis-ish 6-stop ramp, low -> high suitability
const RAMP: [number, number, number][] = [
  [68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37], [255, 255, 200],
];
function colorFor(score: number, alpha = 200): [number, number, number, number] {
  const t = Math.max(0, Math.min(0.999, score));
  const [r, g, b] = RAMP[Math.floor(t * RAMP.length)];
  return [r, g, b, alpha];
}

export interface ViewTarget { longitude: number; latitude: number; zoom: number }

interface Props {
  config: ScoringConfig;
  registry: Registry;
  hexRows: Record<string, unknown>[];
  parcelScores: Map<string, Record<string, unknown>>;
  parcelsGeojson: unknown | null;
  viewTarget: ViewTarget;
}

export default function MapView({ config, registry, hexRows, parcelScores, parcelsGeojson, viewTarget }: Props) {
  const layers = config.displayMode === 'hex'
    ? [new H3HexagonLayer({
        id: `hex-${config.resolution}`,
        data: hexRows,
        getHexagon: (d: Record<string, unknown>) => String(d.h3),
        getFillColor: (d: Record<string, unknown>) =>
          Number(d.mask_factor) === 0 ? [70, 70, 78, 160] : colorFor(Number(d.score)),
        extruded: false, stroked: false, pickable: true,
        updateTriggers: { getFillColor: [hexRows] },
      })]
    : [new GeoJsonLayer({
        id: 'parcels',
        data: parcelsGeojson as never,
        getFillColor: (f: { properties: { parcel_id: string } }) => {
          const row = parcelScores.get(f.properties.parcel_id);
          return row ? colorFor(Number(row.score)) : [40, 40, 46, 120];
        },
        getLineColor: [20, 20, 24, 255], lineWidthMinPixels: 0.3,
        pickable: true,
        updateTriggers: { getFillColor: [parcelScores] },
      })];

  return (
    <div className="map-wrap">
      <DeckGL
        initialViewState={{ ...viewTarget, pitch: 0, bearing: 0 }}
        controller
        layers={layers}
        getTooltip={({ object }: { object?: Record<string, unknown> }) => {
          if (!object) return null;
          const row = 'properties' in object
            ? parcelScores.get(String((object.properties as { parcel_id: string }).parcel_id))
            : object;
          if (!row) return null;
          const breakdown = registry.criteria
            .map((c) => `${c.label}: ${Number(row[`m_${c.key}`]).toFixed(2)}`)
            .join('\n');
          return { text: `score ${Number(row.score).toFixed(3)}\n${breakdown}` };
        }}
      />
    </div>
  );
}
```

- [ ] **Step 3: Write `app/src/components/RankTable.tsx`**

```tsx
import type { Registry } from '../types';

const TOP_N = 500; // table shows the head; exports include every parcel

interface Props {
  registry: Registry;
  rows: Record<string, unknown>[];
  onRowClick: (parcelId: string) => void;
  onExportCSV: () => void;
  onExportGeoJSON: () => void;
}

export default function RankTable({ registry, rows, onRowClick, onExportCSV, onExportGeoJSON }: Props) {
  return (
    <div className="rank-dock">
      <div className="controls-row" style={{ padding: '6px 8px' }}>
        <strong>Ranked parcels</strong>
        <span>top {Math.min(TOP_N, rows.length)} of {rows.length.toLocaleString()} shown — exports include all</span>
        <span style={{ flex: 1 }} />
        <button onClick={onExportCSV}>Export CSV</button>
        <button className="secondary" onClick={onExportGeoJSON}>Export GeoJSON</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>#</th><th>Parcel</th><th>Owner</th><th>Acres</th><th>Score</th><th>Masked</th>
            {registry.criteria.map((c) => <th key={c.key}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, TOP_N).map((r, i) => (
            <tr key={String(r.parcel_id)} onClick={() => onRowClick(String(r.parcel_id))}
                style={{ cursor: 'pointer' }}>
              <td>{i + 1}</td>
              <td>{String(r.parcel_id)}</td>
              <td style={{ textAlign: 'left' }}>{String(r.FullOwnerName ?? '')}</td>
              <td>{Number(r.acres).toFixed(1)}</td>
              <td><strong>{Number(r.score).toFixed(3)}</strong></td>
              <td className={Number(r.masked_frac) > 0 ? 'masked-flag' : ''}>
                {Number(r.masked_frac) > 0 ? `${(Number(r.masked_frac) * 100).toFixed(0)}%` : '—'}
              </td>
              {registry.criteria.map((c) => (
                <td key={c.key}>{Number(r[`m_${c.key}`]).toFixed(2)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Type-check and commit**

```bash
cd app && npx tsc -b
git add app/src/components/MapView.tsx app/src/components/RankTable.tsx app/src/exports.ts
git commit -m "feat: MapView, RankTable, and CSV/GeoJSON exports"
```

---

### Task 7: App shell wiring + live smoke

**Files:**
- Modify: `app/src/App.tsx` (replace placeholder)

- [ ] **Step 1: Write the real `app/src/App.tsx`**

```tsx
import { cellToLatLng } from 'h3-js';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import MapView, { type ViewTarget } from './components/MapView';
import RankTable from './components/RankTable';
import WeightPanel from './components/WeightPanel';
import { initDB, query } from './db';
import { exportCSV, exportGeoJSON } from './exports';
import { defaultConfig, loadRegistry } from './registry';
import { buildHexAggSQL, buildParcelScoreSQL } from './scoring';
import type { ScoringConfig } from './types';

const registry = loadRegistry();

type Phase = { state: 'loading'; msg: string } | { state: 'error'; msg: string } | { state: 'ready' };

export default function App() {
  const [phase, setPhase] = useState<Phase>({ state: 'loading', msg: 'Starting DuckDB…' });
  const [config, setConfig] = useState<ScoringConfig>(() => defaultConfig(registry));
  const [hexRows, setHexRows] = useState<Record<string, unknown>[]>([]);
  const [parcelRows, setParcelRows] = useState<Record<string, unknown>[]>([]);
  const [parcelsGeojson, setParcelsGeojson] = useState<unknown | null>(null);
  const [viewTarget, setViewTarget] = useState<ViewTarget>({ longitude: -81.2, latitude: 37.75, zoom: 9 });
  const debounceRef = useRef<number>(0);

  useEffect(() => {
    (async () => {
      try {
        await initDB();
        setPhase({ state: 'loading', msg: 'Loading parcel geometry…' });
        const gj = await (await fetch('/parcels.geojson')).json();
        setParcelsGeojson(gj);
        const [center] = await query(`SELECT h3_index FROM cells WHERE in_county LIMIT 1`);
        const [lat, lng] = cellToLatLng(String(center.h3_index));
        setViewTarget({ longitude: lng, latitude: lat, zoom: 9.3 });
        setPhase({ state: 'ready' });
      } catch (e) {
        setPhase({ state: 'error', msg: e instanceof Error ? e.message : String(e) });
      }
    })();
  }, []);

  const rescore = useCallback((cfg: ScoringConfig) => {
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(async () => {
      try {
        const t0 = performance.now();
        const [hex, parcels] = await Promise.all([
          query(buildHexAggSQL(registry, cfg)),
          query(buildParcelScoreSQL(registry, cfg)),
        ]);
        setHexRows(hex);
        setParcelRows(parcels);
        console.log(`rescore: ${(performance.now() - t0).toFixed(0)} ms ` +
          `(${hex.length} hexes, ${parcels.length} parcels)`);
      } catch (e) {
        setPhase({ state: 'error', msg: e instanceof Error ? e.message : String(e) });
      }
    }, 60);
  }, []);

  useEffect(() => {
    if (phase.state === 'ready') rescore(config);
  }, [phase.state, config, rescore]);

  const parcelScores = useMemo(
    () => new Map(parcelRows.map((r) => [String(r.parcel_id), r])),
    [parcelRows],
  );
  const totalWeight = Object.values(config.weights).reduce((s, w) => s + w, 0);

  if (phase.state === 'loading') return <div className="loading">{phase.msg}</div>;
  if (phase.state === 'error') return <div className="error-screen">{phase.msg}</div>;

  return (
    <div className="app">
      <div className="app-main">
        <WeightPanel registry={registry} config={config} onChange={setConfig} />
        {totalWeight > 0 ? (
          <MapView config={config} registry={registry} hexRows={hexRows}
            parcelScores={parcelScores} parcelsGeojson={parcelsGeojson} viewTarget={viewTarget} />
        ) : (
          <div className="map-wrap loading">All weights are zero — raise at least one slider.</div>
        )}
      </div>
      <RankTable registry={registry} rows={parcelRows}
        onRowClick={(id) => {
          const row = parcelRows.find((r) => String(r.parcel_id) === id);
          if (!row) return;
          // zoom via the parcel's first crosswalk cell (geometry stays in the geojson layer)
          query(`SELECT h3_index FROM xwalk WHERE parcel_id = '${id.replace(/'/g, "''")}'
                 ORDER BY overlap_frac DESC LIMIT 1`).then(([r]) => {
            if (!r) return;
            const [lat, lng] = cellToLatLng(String(r.h3_index));
            setViewTarget({ longitude: lng, latitude: lat, zoom: 14.5 });
          });
        }}
        onExportCSV={() => exportCSV(parcelRows, registry)}
        onExportGeoJSON={() => parcelsGeojson &&
          exportGeoJSON(parcelRows, parcelsGeojson as never)}
      />
    </div>
  );
}
```

Known limitation to leave as-is (MVP): changing `viewTarget` only re-centers on parcel click because `initialViewState` remounts are keyed by object identity in DeckGL ≥9 via the `initialViewState` prop change; if the zoom-to-parcel proves unreliable during smoke, switch `DeckGL` to controlled `viewState` + `onViewStateChange` — a contained change inside `MapView`.

- [ ] **Step 2: Full test suite + build**

```bash
cd app && npx vitest run && npx tsc -b && npx vite build 2>&1 | tail -3
```
Expected: 12 tests passed; clean build.

- [ ] **Step 3: Live smoke (dev server + HTTP checks)**

```bash
cd app && (npx vite --port 5199 &) && sleep 6 && curl -s -o /dev/null -w "index: %{http_code}\n" http://localhost:5199/ && curl -s -o /dev/null -w "parquet: %{http_code} %{size_download} bytes\n" http://localhost:5199/cells_r10.parquet && curl -s -o /dev/null -w "geojson: %{http_code}\n" http://localhost:5199/parcels.geojson
```
Expected: three 200s, parquet ~5.3 MB. Kill the server afterwards (`taskkill //F //IM node.exe` is too broad — find the vite PID via `netstat -ano | grep 5199` and `taskkill //F //PID <pid>`; report if you cannot).

The FULL visual verification (map renders, sliders re-rank) is done by the controller with browser tooling after this task — you only verify HTTP serving + build + tests.

- [ ] **Step 4: Commit**

```bash
git add app/src/App.tsx
git commit -m "feat: app shell — load, debounced re-score, zoom-to-parcel, exports wired"
```

---

### Task 8: Docs + finish

**Files:**
- Modify: `CLAUDE.md` (Commands section), `docs/data-sources.md` (run-log note)

- [ ] **Step 1: Extend the `## Commands` section of `CLAUDE.md`** with:

```markdown
- App dev server: `cd app && npm run dev` (serves `data/processed/54081/` artifacts at /)
- App tests: `cd app && npm test` (golden scoring tests run real DuckDB via @duckdb/node-api)
- App build: `cd app && npm run build`
```

- [ ] **Step 2: Append one line to the 54081 run log in `docs/data-sources.md`:**

```markdown
**2026-09-02 — browser app (Plan 2) implemented**; artifacts consumed unchanged.
```

- [ ] **Step 3: Suite + commit**

```bash
cd app && npx vitest run
git add CLAUDE.md docs/data-sources.md
git commit -m "docs: app commands and run-log note"
```

---

## Out of scope (post-MVP, do not build)

Basemap tiles, saved scenarios, res-12 sub-parcel crosswalk, additional counties/criteria, table virtualization beyond top-500, functional-class road weighting.
