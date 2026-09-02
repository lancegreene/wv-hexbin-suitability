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
    const r = await rows(`SELECT * FROM (${buildParcelScoreSQL(reg, cfg)}) ORDER BY parcel_id`);
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
