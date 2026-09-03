import { describe, expect, it } from 'vitest';
import { deletePreset, listPresets, loadCurrent, loadPreset, parsePreset, reconcile,
  saveCurrent, savePreset, serializePreset } from '../src/persistence';
import { defaultConfig, loadRegistry } from '../src/registry';

const reg = loadRegistry();

function fakeStore(): Storage {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  } as Storage;
}

describe('current-config autosave', () => {
  it('round-trips', () => {
    const store = fakeStore();
    const cfg = { ...defaultConfig(reg), minAcres: 7 };
    saveCurrent(cfg, store);
    expect(loadCurrent(reg, store).minAcres).toBe(7);
  });
  it('corrupt blob falls back to defaults, not a crash', () => {
    const store = fakeStore();
    store.setItem('hexbin.current.v1', '{not json');
    expect(loadCurrent(reg, store)).toEqual(defaultConfig(reg));
  });
});

describe('reconcile', () => {
  it('drops unknown criterion keys and fills missing ones', () => {
    const raw = { ...defaultConfig(reg), weights: { slope: 0.9, bogus: 0.5 } };
    const out = reconcile(raw, reg);
    expect(out.weights.slope).toBe(0.9);
    expect('bogus' in out.weights).toBe(false);
    expect(out.weights.flood).toBeCloseTo(0.15); // filled from defaults
  });
  it('drops a curve override on a steps-default criterion (no curve exists)', () => {
    const raw = { ...defaultConfig(reg),
      normalization: { hwy_access: { mode: 'curve' } } };
    const out = reconcile(raw, reg);
    expect(out.normalization.hwy_access).toBeUndefined();
  });

  it('drops an invalid steps override with the rest intact', () => {
    const raw = { ...defaultConfig(reg),
      normalization: { slope: { mode: 'steps', steps: [{ score: 2, label: '' }] } } };
    const out = reconcile(raw, reg);
    expect(out.normalization.slope).toBeUndefined();
  });
});

describe('presets', () => {
  it('save/list/load/delete', () => {
    const store = fakeStore();
    const cfg = { ...defaultConfig(reg), minAcres: 5 };
    savePreset('industrial', cfg, store);
    expect(listPresets(store).map((p) => p.name)).toEqual(['industrial']);
    expect(loadPreset('industrial', reg, store)?.minAcres).toBe(5);
    deletePreset('industrial', store);
    expect(listPresets(store)).toEqual([]);
  });
  it('export/import round-trip', () => {
    const cfg = { ...defaultConfig(reg), scoreOpacity: 0.55 };
    const text = serializePreset('shared', cfg);
    const parsed = parsePreset(text, reg);
    expect(parsed.name).toBe('shared');
    expect(parsed.config.scoreOpacity).toBeCloseTo(0.55);
  });
  it('import rejects wrong format with a readable error', () => {
    expect(() => parsePreset('{"format":"other"}', reg)).toThrow(/hexbin-preset-v1/);
  });
});
