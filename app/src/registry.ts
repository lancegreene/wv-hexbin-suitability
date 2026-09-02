import registryJson from '../../config/criteria.json';
import { validateSteps } from './steps';
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
    if (!c.unit) {
      throw new Error(`criteria.json: criterion '${c.key}' is missing 'unit'`);
    }
    if (c.membership.fn === 'lookup' && typeof c.membership.miss_score !== 'number') {
      throw new Error(`criteria.json: lookup criterion '${c.key}' needs miss_score — ` +
        `an unmatched class must score, not go NULL`);
    }
    if (c.membership.fn === 'steps') {
      const errors = validateSteps(c.membership.steps);
      if (errors.length) {
        throw new Error(`criteria.json: invalid default classes for '${c.key}': ${errors.join('; ')}`);
      }
    }
  }
  for (const m of reg.masks) {
    if (!m.key || !m.column || !m.predicate) {
      throw new Error(`criteria.json: mask ${JSON.stringify(m.key)} is incomplete — ` +
        `needs key, column, and predicate`);
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
    minAcres: 0,
    aggregation: 'wlc',
    resolution: 8,
    displayMode: 'hex',
    basemap: 'none',
    scoreOpacity: 0.8,
    normalization: {},
  };
}
