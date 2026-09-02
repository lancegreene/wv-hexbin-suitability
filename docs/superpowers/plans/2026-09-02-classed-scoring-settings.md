# Classed Scoring + Settings Panel Implementation Plan (Phase A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-criterion classed ("steps") scoring with plain-English labels, edited in a right-side settings drawer, persisted via localStorage autosave + named presets + JSON export/import.

**Architecture:** A `normalization` map on `ScoringConfig` overrides the registry's membership per criterion (`curve` = registry default, `steps` = ordered classes). SQL generation resolves the effective membership per criterion — everything downstream (weights, masks, crosswalk) is untouched. Persistence is a standalone module with an injectable Storage so tests run in Node. UI: gear-button drawer; class labels surface in tooltip, table, and CSV.

**Tech Stack:** existing deps only. Branch: `classes`. Repo `hexbin`; app commands `cd app && npx ...`; ALL commands FOREGROUND with explicit timeouts.

**Reference:** spec `docs/superpowers/specs/2026-09-02-classed-scoring-settings-design.md`.

---

## File structure

```
config/criteria.json                 # + additive `unit` field per criterion
app/src/types.ts                     # Step, NormalizationOverride, ScoringConfig.normalization, unit on Criterion
app/src/steps.ts                     # NEW: validation, unit conversions, labelForScore
app/src/registry.ts                  # defaultConfig gains normalization: {}
app/src/scoring.ts                   # effectiveMembership() + steps CASE SQL
app/src/persistence.ts               # NEW: autosave, presets, export/import, reconcile
app/src/components/SettingsDrawer.tsx# NEW: the drawer
app/src/components/MapView.tsx       # tooltip labels for stepped criteria
app/src/components/RankTable.tsx     # label under value for stepped criteria
app/src/exports.ts                   # <key>_class CSV columns
app/src/App.tsx                      # load/autosave config, gear button, drawer mount
app/src/styles.css                   # drawer styles
app/tests/steps.test.ts              # NEW
app/tests/persistence.test.ts        # NEW
app/tests/scoring.test.ts            # steps golden additions
```

Baseline: 15 app tests. Targets: Task 1 → 25, Task 2 → 28, Task 3 → 35 (the counts in each task's run step are the contract).

---

### Task 1: Types, units, steps helpers (TDD)

**Files:**
- Modify: `config/criteria.json`, `app/src/types.ts`, `app/src/registry.ts`
- Create: `app/src/steps.ts`
- Test: `app/tests/steps.test.ts`

- [ ] **Step 1: Write failing tests `app/tests/steps.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import { degToPct, labelForScore, metersToMiles, milesToMeters, pctToDeg, validateSteps } from '../src/steps';
import type { Step } from '../src/types';

const GOOD: Step[] = [
  { max: 8.75, score: 1.0, label: 'no limitations' },
  { max: 17.63, score: 0.5, label: 'some grading' },
  { score: 0.0, label: 'not advised' },
];

describe('validateSteps', () => {
  it('accepts a valid 3-class scheme', () => expect(validateSteps(GOOD)).toEqual([]));
  it('rejects fewer than 2 classes', () =>
    expect(validateSteps([{ score: 1, label: 'x' }])).not.toEqual([]));
  it('rejects missing catch-all', () =>
    expect(validateSteps([{ max: 1, score: 1, label: 'a' }, { max: 2, score: 0, label: 'b' }])
      .join()).toMatch(/catch-all/));
  it('rejects a catch-all not in last position', () =>
    expect(validateSteps([{ score: 0, label: 'z' }, { max: 5, score: 1, label: 'a' }])
      .join()).toMatch(/last/));
  it('rejects non-ascending bounds', () =>
    expect(validateSteps([{ max: 10, score: 1, label: 'a' }, { max: 5, score: 0.5, label: 'b' },
      { score: 0, label: 'c' }]).join()).toMatch(/ascending/));
  it('rejects out-of-range scores and empty labels', () => {
    expect(validateSteps([{ max: 1, score: 1.5, label: 'a' }, { score: 0, label: 'b' }])
      .join()).toMatch(/\[0,1\]/);
    expect(validateSteps([{ max: 1, score: 1, label: '  ' }, { score: 0, label: 'b' }])
      .join()).toMatch(/label/);
  });
});

describe('unit conversions', () => {
  it('5 degrees is ~8.75 percent slope, and round-trips', () => {
    expect(degToPct(5)).toBeCloseTo(8.7489, 3);
    expect(pctToDeg(degToPct(23.4))).toBeCloseTo(23.4, 9);
  });
  it('miles round-trip', () =>
    expect(metersToMiles(milesToMeters(3.2))).toBeCloseTo(3.2, 9));
});

describe('labelForScore', () => {
  it('exact match', () =>
    expect(labelForScore(GOOD, 0.5)).toEqual({ label: 'some grading', exact: true }));
  it('nearest match flagged inexact', () =>
    expect(labelForScore(GOOD, 0.72)).toEqual({ label: 'some grading', exact: false }));
});
```

Run `cd app && npx vitest run tests/steps.test.ts` → FAIL (no module). Report red.

- [ ] **Step 2: `app/src/types.ts` additions**

```ts
export interface Step {
  max?: number;  // inclusive upper bound in the column's stored unit; absent = catch-all (must be last)
  score: number; // 0-1
  label: string; // plain-English class meaning, surfaces in tooltip/table/CSV
}

export type NormalizationOverride =
  | { mode: 'curve' }
  | { mode: 'steps'; steps: Step[] };
```

`Criterion` gains `unit: 'pct_slope' | 'pct' | 'meters' | 'binary' | 'category';`
`ScoringConfig` gains `normalization: Record<string, NormalizationOverride>;`

- [ ] **Step 3: `config/criteria.json`** — add `"unit"` to each criterion: slope `"pct_slope"`, flood `"pct"`, water `"binary"`, roads `"meters"`, transmission `"meters"`, landcover `"category"`. Nothing else changes.

- [ ] **Step 4: `app/src/registry.ts`** — `defaultConfig` gains `normalization: {},`; `loadRegistry` additionally rejects a criterion without a `unit` (message names the key).

- [ ] **Step 5: Write `app/src/steps.ts`**

```ts
import type { Step } from './types';

/** Returns [] when valid, else human-readable problems (shown inline in the drawer). */
export function validateSteps(steps: Step[]): string[] {
  const errors: string[] = [];
  if (steps.length < 2) errors.push('need at least 2 classes');
  const catchalls = steps.filter((s) => s.max === undefined);
  if (catchalls.length !== 1) errors.push('exactly one catch-all class (no upper bound) required');
  else if (steps.length && steps[steps.length - 1].max !== undefined) {
    errors.push('the catch-all class must be last');
  }
  let prev = -Infinity;
  for (const s of steps) {
    if (s.max !== undefined) {
      if (!Number.isFinite(s.max)) errors.push(`bound ${s.max} is not a finite number`);
      else if (s.max <= prev) errors.push(`bounds must be strictly ascending (${s.max} after ${prev})`);
      if (Number.isFinite(s.max)) prev = s.max;
    }
    if (!Number.isFinite(s.score) || s.score < 0 || s.score > 1) {
      errors.push(`score ${s.score} outside [0,1]`);
    }
    if (!s.label.trim()) errors.push('every class needs a label');
  }
  return errors;
}

export const degToPct = (deg: number): number => Math.tan((deg * Math.PI) / 180) * 100;
export const pctToDeg = (pct: number): number => (Math.atan(pct / 100) * 180) / Math.PI;
export const milesToMeters = (mi: number): number => mi * 1609.344;
export const metersToMiles = (m: number): number => m / 1609.344;

/** Class label whose score is nearest the (possibly averaged) shown value. */
export function labelForScore(steps: Step[], score: number): { label: string; exact: boolean } {
  let best = steps[0];
  let bestD = Infinity;
  for (const s of steps) {
    const d = Math.abs(s.score - score);
    if (d < bestD) { bestD = d; best = s; }
  }
  return { label: best.label, exact: bestD < 1e-9 };
}
```

- [ ] **Step 6: Green + commit**

```bash
cd app && npx vitest run && npx tsc -b   # expect 25 passed (15 + 10 new), clean
git add config/criteria.json app/src/types.ts app/src/registry.ts app/src/steps.ts app/tests/steps.test.ts
git commit -m "feat: step-class data model, unit metadata, validation and conversions"
```

---

### Task 2: Steps SQL generation (TDD golden)

**Files:**
- Modify: `app/src/scoring.ts`
- Test: `app/tests/scoring.test.ts`

- [ ] **Step 1: Add failing golden tests** to `app/tests/scoring.test.ts` (uses the existing fixture — cells a/b/c have slope 20/20/60, road_dist 1500):

```ts
describe('steps normalization', () => {
  const SLOPE_STEPS = { mode: 'steps' as const, steps: [
    { max: 8.75, score: 1.0, label: 'no limitations' },
    { max: 17.63, score: 0.5, label: 'some grading' },
    { score: 0.0, label: 'not advised' },
  ]};

  it('bounds are inclusive: a value exactly at max lands in that class', async () => {
    const cfgSteps = { ...cfg, normalization: { roads: { mode: 'steps' as const, steps: [
      { max: 1500, score: 1.0, label: 'close' }, { score: 0.0, label: 'far' },
    ]}}};
    const r = await rows(`${buildCellScoreSQL(reg, cfgSteps)} ORDER BY h3_index`);
    expect(Number(r[0].m_roads)).toBeCloseTo(1.0, 9); // road_dist_m = 1500 exactly
  });

  it('slope classes replace the curve; hand-computed cell/parcel scores', async () => {
    const cfgSteps = { ...cfg, normalization: { slope: SLOPE_STEPS } };
    const r = await rows(`${buildCellScoreSQL(reg, cfgSteps)} ORDER BY h3_index`);
    // cell a: slope 20 > 17.63 -> m_slope 0. WLC = .2*0+.15*1+.2*1+.15*.5+.15*.5+.15*1 = 0.65
    expect(Number(r[0].m_slope)).toBeCloseTo(0.0, 9);
    expect(Number(r[0].score)).toBeCloseTo(0.65, 6);
    const p = await rows(`SELECT * FROM (${buildParcelScoreSQL(reg, cfgSteps)}) ORDER BY parcel_id`);
    expect(Number(p[0].score)).toBeCloseTo(0.65, 6);   // P1 = 100% cell a
  });

  it('invalid steps throw before any SQL is generated', () => {
    const bad = { ...cfg, normalization: { slope: { mode: 'steps' as const, steps: [
      { max: 10, score: 1, label: 'a' }] } } };
    expect(() => buildCellScoreSQL(reg, bad)).toThrow(/invalid classes for slope/);
  });
});
```

Run → FAIL (`normalization` unused; m_slope still 0.5-curve etc.). Report red.

- [ ] **Step 2: `app/src/scoring.ts`** — add:

```ts
import { validateSteps } from './steps';
import type { Criterion, NormalizationOverride } from './types';

/** SQL for one criterion honoring any steps override; curve = registry membership. */
export function effectiveMembershipSQL(c: Criterion, override: NormalizationOverride | undefined): string {
  if (override?.mode === 'steps') {
    const errors = validateSteps(override.steps);
    if (errors.length) {
      throw new Error(`invalid classes for ${c.key}: ${errors.join('; ')}`);
    }
    const bounded = override.steps.filter((s) => s.max !== undefined);
    const catchall = override.steps.find((s) => s.max === undefined)!;
    const whens = bounded.map((s) => `WHEN ${c.column} <= ${s.max} THEN ${s.score}`).join(' ');
    return `(CASE ${whens} ELSE ${catchall.score} END)`;
  }
  return membershipSQL(c.membership, c.column);
}
```

In `buildCellScoreSQL`, the memberCols mapping becomes:

```ts
  const memberCols = reg.criteria
    .map((c) => `${effectiveMembershipSQL(c, cfg.normalization[c.key])} AS m_${c.key}`)
    .join(',\n    ');
```

- [ ] **Step 3: Green + commit**

```bash
cd app && npx vitest run && npx tsc -b   # expect 28 passed
git add app/src/scoring.ts app/tests/scoring.test.ts
git commit -m "feat: steps membership SQL with inclusive bounds and validation"
```

---

### Task 3: Persistence module (TDD)

**Files:**
- Create: `app/src/persistence.ts`
- Test: `app/tests/persistence.test.ts`

- [ ] **Step 1: Write failing tests `app/tests/persistence.test.ts`**

```ts
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
```

Run → FAIL (no module). Report red.

- [ ] **Step 2: Write `app/src/persistence.ts`**

```ts
import { defaultConfig } from './registry';
import { validateSteps } from './steps';
import type { NormalizationOverride, Registry, ScoringConfig } from './types';

const CURRENT_KEY = 'hexbin.current.v1';
const PRESETS_KEY = 'hexbin.presets.v1';

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const browserStore = (): Store => window.localStorage;

/** Overlay a raw (untrusted) config onto registry defaults, dropping anything invalid. */
export function reconcile(raw: unknown, reg: Registry): ScoringConfig {
  const out = defaultConfig(reg);
  if (typeof raw !== 'object' || raw === null) return out;
  const r = raw as Partial<ScoringConfig> & Record<string, unknown>;
  const known = new Set(reg.criteria.map((c) => c.key));

  if (r.weights && typeof r.weights === 'object') {
    for (const [k, v] of Object.entries(r.weights)) {
      if (known.has(k) && typeof v === 'number' && Number.isFinite(v) && v >= 0) out.weights[k] = v;
      else if (!known.has(k)) console.warn(`preset: dropping unknown criterion weight '${k}'`);
    }
  }
  if (r.masksEnabled && typeof r.masksEnabled === 'object') {
    for (const m of reg.masks) {
      const v = (r.masksEnabled as Record<string, unknown>)[m.key];
      if (typeof v === 'boolean') out.masksEnabled[m.key] = v;
    }
  }
  if (typeof r.slopeThreshold === 'number' && Number.isFinite(r.slopeThreshold)) out.slopeThreshold = r.slopeThreshold;
  if (typeof r.minAcres === 'number' && Number.isFinite(r.minAcres) && r.minAcres >= 0) out.minAcres = r.minAcres;
  if (typeof r.scoreOpacity === 'number' && r.scoreOpacity > 0 && r.scoreOpacity <= 1) out.scoreOpacity = r.scoreOpacity;
  if (r.aggregation === 'wlc' || r.aggregation === 'geometric') out.aggregation = r.aggregation;
  if (r.resolution === 8 || r.resolution === 9 || r.resolution === 10) out.resolution = r.resolution;
  if (r.displayMode === 'hex' || r.displayMode === 'parcel') out.displayMode = r.displayMode;
  if (r.basemap === 'none' || r.basemap === 'streets' || r.basemap === 'imagery') out.basemap = r.basemap;

  if (r.normalization && typeof r.normalization === 'object') {
    for (const [k, ov] of Object.entries(r.normalization as Record<string, NormalizationOverride>)) {
      if (!known.has(k)) { console.warn(`preset: dropping normalization for unknown '${k}'`); continue; }
      if (ov?.mode === 'curve') out.normalization[k] = ov;
      else if (ov?.mode === 'steps' && Array.isArray(ov.steps) && validateSteps(ov.steps).length === 0) {
        out.normalization[k] = ov;
      } else console.warn(`preset: dropping invalid classes for '${k}'`);
    }
  }
  return out;
}

export function saveCurrent(cfg: ScoringConfig, store: Store = browserStore()): void {
  store.setItem(CURRENT_KEY, JSON.stringify(cfg));
}

export function loadCurrent(reg: Registry, store: Store = browserStore()): ScoringConfig {
  const raw = store.getItem(CURRENT_KEY);
  if (raw === null) return defaultConfig(reg);
  try {
    return reconcile(JSON.parse(raw), reg);
  } catch {
    console.warn('persistence: stored config unreadable, using defaults');
    return defaultConfig(reg);
  }
}

interface PresetEntry { name: string; savedAt: string; config: ScoringConfig }

function readPresets(store: Store): PresetEntry[] {
  try {
    const raw = store.getItem(PRESETS_KEY);
    return raw ? (JSON.parse(raw) as PresetEntry[]) : [];
  } catch {
    console.warn('persistence: preset store unreadable, starting empty');
    return [];
  }
}

export function listPresets(store: Store = browserStore()): { name: string; savedAt: string }[] {
  return readPresets(store).map(({ name, savedAt }) => ({ name, savedAt }));
}

export function savePreset(name: string, cfg: ScoringConfig, store: Store = browserStore()): void {
  const presets = readPresets(store).filter((p) => p.name !== name);
  presets.push({ name, savedAt: new Date().toISOString(), config: cfg });
  store.setItem(PRESETS_KEY, JSON.stringify(presets));
}

export function loadPreset(name: string, reg: Registry, store: Store = browserStore()): ScoringConfig | null {
  const hit = readPresets(store).find((p) => p.name === name);
  return hit ? reconcile(hit.config, reg) : null;
}

export function deletePreset(name: string, store: Store = browserStore()): void {
  store.setItem(PRESETS_KEY, JSON.stringify(readPresets(store).filter((p) => p.name !== name)));
}

export function serializePreset(name: string, cfg: ScoringConfig): string {
  return JSON.stringify(
    { format: 'hexbin-preset-v1', name, savedAt: new Date().toISOString(), config: cfg },
    null, 2);
}

export function parsePreset(text: string, reg: Registry): { name: string; config: ScoringConfig } {
  let obj: unknown;
  try {
    obj = JSON.parse(text);
  } catch {
    throw new Error('not valid JSON');
  }
  const p = obj as { format?: string; name?: string; config?: unknown };
  if (p.format !== 'hexbin-preset-v1') {
    throw new Error(`unrecognized file — expected format "hexbin-preset-v1", got "${p.format}"`);
  }
  if (!p.name || typeof p.name !== 'string') throw new Error('preset has no name');
  return { name: p.name, config: reconcile(p.config, reg) };
}
```

Note for the test environment: `new Date()` is fine in app code and vitest.
`browserStore()` touches `window` only when a store isn't injected — all
tests inject `fakeStore()`, so Node stays happy.

- [ ] **Step 3: Green + commit**

```bash
cd app && npx vitest run && npx tsc -b   # expect 35 passed (28 + 7 new)
git add app/src/persistence.ts app/tests/persistence.test.ts
git commit -m "feat: config autosave, named presets, preset file export/import"
```

---

### Task 4: Settings drawer + wiring + labels

**Files:**
- Create: `app/src/components/SettingsDrawer.tsx`
- Modify: `app/src/App.tsx`, `app/src/components/MapView.tsx`, `app/src/components/RankTable.tsx`, `app/src/exports.ts`, `app/src/styles.css`

- [ ] **Step 1: Write `app/src/components/SettingsDrawer.tsx`**

```tsx
import { useRef, useState } from 'react';
import { deletePreset, listPresets, loadPreset, parsePreset, savePreset, serializePreset } from '../persistence';
import { degToPct, metersToMiles, milesToMeters, pctToDeg, validateSteps } from '../steps';
import type { Criterion, Registry, ScoringConfig, Step } from '../types';

interface Props {
  registry: Registry;
  config: ScoringConfig;
  onChange: (cfg: ScoringConfig) => void;
  onClose: () => void;
}

const EDITABLE_UNITS = new Set(['pct_slope', 'pct', 'meters']);

function toDisplay(unit: string, stored: number): number {
  if (unit === 'pct_slope') return pctToDeg(stored);
  if (unit === 'meters') return metersToMiles(stored);
  return stored;
}
function fromDisplay(unit: string, shown: number): number {
  if (unit === 'pct_slope') return degToPct(shown);
  if (unit === 'meters') return milesToMeters(shown);
  return shown;
}
const unitLabel = (unit: string) => (unit === 'pct_slope' ? '°' : unit === 'meters' ? 'mi' : '%');

function StepsEditor({ c, steps, onSteps }: {
  c: Criterion; steps: Step[]; onSteps: (s: Step[]) => void;
}) {
  const errors = validateSteps(steps);
  const set = (i: number, patch: Partial<Step>) =>
    onSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  return (
    <div className="steps-editor">
      <table>
        <thead><tr><th>≤ bound ({unitLabel(c.unit)})</th><th>score</th><th>label</th><th /></tr></thead>
        <tbody>
          {steps.map((s, i) => (
            <tr key={i}>
              <td>
                {s.max === undefined ? <em>above</em> : (
                  <input type="number" step="any"
                    value={Number(toDisplay(c.unit, s.max).toFixed(3))}
                    onChange={(e) => set(i, { max: fromDisplay(c.unit, Number(e.target.value)) })} />
                )}
              </td>
              <td>
                <input type="number" min={0} max={1} step={0.05} value={s.score}
                  onChange={(e) => set(i, { score: Number(e.target.value) })} />
              </td>
              <td>
                <input type="text" value={s.label}
                  onChange={(e) => set(i, { label: e.target.value })} />
              </td>
              <td>
                {s.max !== undefined && (
                  <button className="secondary" onClick={() => onSteps(steps.filter((_, j) => j !== i))}>×</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="secondary" onClick={() => {
        const lastBound = steps.filter((s) => s.max !== undefined).pop();
        const newMax = (lastBound?.max ?? 0) * 2 || fromDisplay(c.unit, 1);
        onSteps([...steps.slice(0, -1), { max: newMax, score: 0.5, label: 'new class' }, steps[steps.length - 1]]);
      }}>+ class</button>
      {errors.length > 0 && (
        <div className="steps-errors">{errors.map((e, i) => <div key={i}>{e}</div>)}</div>
      )}
      <div className="muted">stored bounds: {steps.filter((s) => s.max !== undefined)
        .map((s) => `${s.max?.toFixed(1)}`).join(', ')} ({c.unit})</div>
    </div>
  );
}

export default function SettingsDrawer({ registry, config, onChange, onClose }: Props) {
  const [presetName, setPresetName] = useState('');
  const [importError, setImportError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const defaultStepsFor = (c: Criterion): Step[] =>
    c.unit === 'pct_slope'
      ? [{ max: degToPct(5), score: 1.0, label: 'no limitations' },
         { max: degToPct(10), score: 0.5, label: 'some limitations' },
         { score: 0.0, label: 'not advised' }]
      : [{ max: fromDisplay(c.unit, 1), score: 1.0, label: 'good' },
         { max: fromDisplay(c.unit, 3), score: 0.5, label: 'fair' },
         { score: 0.0, label: 'poor' }];

  return (
    <div className="drawer">
      <div className="drawer-head">
        <strong>Scoring settings</strong>
        <button className="secondary" onClick={onClose}>close</button>
      </div>

      {registry.criteria.filter((c) => EDITABLE_UNITS.has(c.unit)).map((c) => {
        const ov = config.normalization[c.key];
        const stepped = ov?.mode === 'steps';
        return (
          <section className="panel-card" key={c.key}>
            <div className="group-title">{c.label}</div>
            <div className="controls-row">
              <label><input type="radio" checked={!stepped}
                onChange={() => {
                  const { [c.key]: _drop, ...rest } = config.normalization;
                  onChange({ ...config, normalization: rest });
                }} /> Curve</label>
              <label><input type="radio" checked={stepped}
                onChange={() => onChange({ ...config, normalization: {
                  ...config.normalization, [c.key]: { mode: 'steps', steps: defaultStepsFor(c) } } })} /> Classes</label>
            </div>
            {stepped ? (
              <StepsEditor c={c} steps={(ov as { steps: Step[] }).steps}
                onSteps={(steps) => onChange({ ...config, normalization: {
                  ...config.normalization, [c.key]: { mode: 'steps', steps } } })} />
            ) : (
              <div className="muted">
                {c.membership.fn === 'small'
                  ? `curve: 0.5 at ${toDisplay(c.unit, c.membership.midpoint).toFixed(1)}${unitLabel(c.unit)}`
                  : `curve: ${c.membership.fn}`}
              </div>
            )}
          </section>
        );
      })}

      <section className="panel-card">
        <div className="group-title">Presets</div>
        <div className="controls-row">
          <input type="text" placeholder="preset name" value={presetName}
            onChange={(e) => setPresetName(e.target.value)} />
          <button disabled={!presetName.trim()}
            onClick={() => { savePreset(presetName.trim(), config); setPresetName(''); }}>
            Save as
          </button>
        </div>
        {listPresets().map((p) => (
          <div className="controls-row" key={p.name}>
            <span style={{ flex: 1 }}>{p.name}</span>
            <button className="secondary" onClick={() => {
              const cfg = loadPreset(p.name, registry);
              if (cfg) onChange(cfg);
            }}>Load</button>
            <button className="secondary" onClick={() => {
              const a = document.createElement('a');
              a.href = URL.createObjectURL(new Blob([serializePreset(p.name, loadPreset(p.name, registry) ?? config)],
                { type: 'application/json' }));
              a.download = `${p.name}.suitability-preset.json`;
              document.body.appendChild(a); a.click(); a.remove();
              setTimeout(() => URL.revokeObjectURL(a.href), 2000);
            }}>Export</button>
            {confirmDelete === p.name ? (
              <button onClick={() => { deletePreset(p.name); setConfirmDelete(null); }}>confirm ×</button>
            ) : (
              <button className="secondary" onClick={() => setConfirmDelete(p.name)}>×</button>
            )}
          </div>
        ))}
        <div className="controls-row">
          <button className="secondary" onClick={() => fileRef.current?.click()}>Import preset file…</button>
          <input ref={fileRef} type="file" accept=".json" style={{ display: 'none' }}
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              try {
                const parsed = parsePreset(await f.text(), registry);
                savePreset(parsed.name, parsed.config);
                setImportError(null);
              } catch (err) {
                setImportError(err instanceof Error ? err.message : String(err));
              } finally {
                e.target.value = '';
              }
            }} />
        </div>
        {importError && <div className="steps-errors">import failed: {importError}</div>}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: `App.tsx` wiring**

a. Imports: `loadCurrent`, `saveCurrent` from `./persistence`; `SettingsDrawer` component; `validateSteps` not needed here.
b. Initial state: `useState<ScoringConfig>(() => loadCurrent(registry))` (replaces `defaultConfig(registry)`).
c. Autosave effect:

```tsx
  useEffect(() => {
    const t = window.setTimeout(() => saveCurrent(config), 300);
    return () => window.clearTimeout(t);
  }, [config]);
```

d. Drawer state `const [settingsOpen, setSettingsOpen] = useState(false);`; gear button in the header (before the attribution): `<button className="secondary" onClick={() => setSettingsOpen((v) => !v)}>⚙ settings</button>`; render `{settingsOpen && <SettingsDrawer registry={registry} config={config} onChange={setConfig} onClose={() => setSettingsOpen(false)} />}` inside `.app-main` AFTER `<MapView …>` so it overlays the map's right edge.
e. **Invalid-steps safety:** the rescore effect must not fire broken SQL. Wrap the rescore call:

```tsx
  const stepsValid = Object.entries(config.normalization).every(
    ([, ov]) => ov.mode !== 'steps' || validateSteps(ov.steps).length === 0);
  useEffect(() => {
    if (phase.state === 'ready' && totalWeight > 0 && stepsValid) rescore(config);
  }, [phase.state, config, rescore, totalWeight, stepsValid]);
```
(import `validateSteps` after all; drawer shows the inline errors meanwhile).

- [ ] **Step 3: labels in tooltip — `MapView.tsx`.** In `getTooltip`, when a criterion has a steps override, append its class label:

```tsx
          const breakdown = registry.criteria
            .map((c) => {
              const v = Number(row[`m_${c.key}`]);
              const ov = config.normalization[c.key];
              if (ov?.mode === 'steps') {
                const { label, exact } = labelForScore(ov.steps, v);
                return `${c.label}: ${v.toFixed(2)} — ${exact ? '' : '~'}${label}`;
              }
              return `${c.label}: ${v.toFixed(2)}`;
            })
            .join('\n');
```
(import `labelForScore` from `../steps`.)

- [ ] **Step 4: labels in the table — `RankTable.tsx`.** Add `config: ScoringConfig` to Props (App passes it). The per-criterion cell becomes:

```tsx
              {registry.criteria.map((c) => {
                const v = Number(r[`m_${c.key}`]);
                const ov = config.normalization[c.key];
                const lab = ov?.mode === 'steps' ? labelForScore(ov.steps, v) : null;
                return (
                  <td key={c.key}>
                    {v.toFixed(2)}
                    {lab && <div className="class-label">{lab.exact ? '' : '~'}{lab.label}</div>}
                  </td>
                );
              })}
```

- [ ] **Step 5: export labels — `exports.ts`.** Both exporters gain a `config: ScoringConfig` param (update BOTH call sites in App: `exportCSV(parcelRows, registry, config)` and `exportGeoJSON(parcelRows, parcelsGeojson, config)` — keep the registry param on CSV). For each stepped criterion:
  - CSV: append a `${key}_class` column after the base cols, value `labelForScore(steps, Number(r[`m_${key}`])).label`, prefixed `~` when not exact.
  - GeoJSON: inject the same `${key}_class` values into each merged feature's properties (spec: "GeoJSON export inherits the same properties").

- [ ] **Step 6: styles.css** — append:

```css
.drawer { position: absolute; top: 0; right: 0; bottom: 0; width: 380px; z-index: 20; overflow-y: auto; background: #1c1f26f2; border-left: 1px solid #3a4150; padding: 12px; backdrop-filter: blur(3px); }
.drawer-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.steps-editor table { width: 100%; border-collapse: collapse; }
.steps-editor input[type="number"] { width: 70px; }
.steps-editor input[type="text"] { width: 100%; }
.steps-editor td, .steps-editor th { padding: 2px 4px; text-align: left; }
.steps-errors { color: #ff7b72; font-size: 12px; margin-top: 4px; white-space: pre-wrap; }
.class-label { font-size: 10px; color: #8a919e; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```
`.app-main` needs `position: relative;` added so the drawer anchors to it.

- [ ] **Step 7: Verify + commit**

```bash
cd app && npx vitest run && npx tsc -b && npx vite build 2>&1 | tail -3   # 36 passed, clean
git add app/src
git commit -m "feat: settings drawer, class labels in tooltip/table/CSV, config autosave"
```

---

### Task 5: Live verification + docs (controller-led)

- [ ] Controller drives Chrome: open drawer; switch Slope to Classes (defaults land as 5°/10° tiers); confirm live re-rank and gray/purple shift; edit a bound; introduce an invalid bound → inline error, no crash, no rescore; labels visible in tooltip + table; save preset "classed-example"; export it; reload page → config restored; import the exported file; CSV export contains `slope_class`.
- [ ] Run-log line in `docs/data-sources.md`; commit; final review; merge per finishing-a-development-branch.

## Out of scope
Phase B (`hwy_drive_min`); NLCD/water class editing; drawer-based weight editing; preset cloud sync.
