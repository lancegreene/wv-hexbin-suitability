import { validateSteps } from './steps';
import type { Criterion, MembershipFn, NormalizationOverride, Registry, ScoringConfig } from './types';

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
    case 'steps': {
      const bounded = m.steps.filter((s) => s.max !== undefined);
      const catchall = m.steps.find((s) => s.max === undefined)!;
      const whens = bounded.map((s) => `WHEN ${column} <= ${s.max} THEN ${s.score}`).join(' ');
      return `(CASE ${whens} ELSE ${catchall.score} END)`;
    }
  }
}

/** SQL for one criterion honoring any steps override; curve/registry-default steps = registry membership. */
export function effectiveMembershipSQL(c: Criterion, override: NormalizationOverride | undefined): string {
  if (override?.mode === 'steps') {
    const errors = validateSteps(override.steps);
    if (errors.length) {
      throw new Error(`invalid classes for ${c.key}: ${errors.join('; ')}`);
    }
    return membershipSQL({ fn: 'steps', steps: override.steps }, c.column);
  }
  return membershipSQL(c.membership, c.column);
}

function maskFactorSQL(reg: Registry, cfg: ScoringConfig): string {
  if (!Number.isFinite(cfg.slopeThreshold)) {
    throw new Error(`invalid slope threshold: ${cfg.slopeThreshold} — must be a finite number`);
  }
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
    .map((c) => `${effectiveMembershipSQL(c, cfg.normalization[c.key])} AS m_${c.key}`)
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
  if (!Number.isFinite(cfg.minAcres) || cfg.minAcres < 0) {
    throw new Error(`invalid minimum acreage: ${cfg.minAcres}`);
  }
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
WHERE p.acres >= ${cfg.minAcres}
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
  // AVG, not MIN: a res-8 parent has ~49 children, and MIN painted a parent
  // "masked" if ANY child was — mislabeling 66% of Raleigh County as excluded
  // when only 17% actually is (falsified by real data during final review)
  return `
SELECT ${parent} AS h3, AVG(score) AS score, AVG(mask_factor) AS mask_factor, ${memberAvgs}
FROM (${scored}) WHERE in_county GROUP BY ${parent}`;
}
