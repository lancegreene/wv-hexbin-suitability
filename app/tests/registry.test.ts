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
