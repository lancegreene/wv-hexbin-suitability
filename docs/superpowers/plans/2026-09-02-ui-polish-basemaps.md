# UI Polish + Base Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Esri basemaps (none/streets/imagery) under the score layers with floating map chrome (basemap+opacity card, legend), a county outline, a slim header with attribution, and the left panel restyled into section cards.

**Architecture:** Display-only changes — no scoring SQL is touched. Two new `ScoringConfig` fields (`basemap`, `scoreOpacity`) flow from App → MapView exactly like existing config. The county outline comes from a new pipeline artifact `county_boundary.geojson`: the **grid stage writes it** to `data/work/<fips>/` (it already holds the county polygon) and **validate gates + publishes it** like the parcel files — this keeps validate free of raw-data reads so its tests stay hermetic (deviation from the spec's "validate publishes" wording, same artifact contract).

**Tech Stack:** existing app deps only — `TileLayer`/`BitmapLayer` ship inside the installed deck.gl packages. No new npm installs.

**Reference:** spec `docs/superpowers/specs/2026-09-02-ui-polish-basemaps-design.md`. Repo root `hexbin`, Git Bash, work on branch `polish`. Pipeline python: `.venv/Scripts/python.exe`; app: `cd app && npx ...`. All commands FOREGROUND with explicit timeouts.

---

## File structure

```
pipeline/hexbin_pipeline/grid.py       # + write county_boundary.geojson to work dir
pipeline/hexbin_pipeline/validate.py   # + gate/publish it
pipeline/tests/test_validate.py        # fixture + assertion
app/src/types.ts                       # + basemap, scoreOpacity
app/src/registry.ts                    # defaults
app/tests/registry.test.ts             # default assertions
app/src/db.ts                          # HEAD-check static files incl. boundary
app/src/components/MapControls.tsx     # NEW: floating basemap + opacity card
app/src/components/Legend.tsx          # NEW: floating legend
app/src/components/MapView.tsx         # tile layers, outline, opacity, chrome mount
app/src/components/WeightPanel.tsx     # section-card wrappers
app/src/App.tsx                        # header bar, chrome wiring
app/src/styles.css                     # header, cards, floating chrome
```

---

### Task 1: Pipeline — county boundary artifact (TDD on the validate gate)

**Files:**
- Modify: `pipeline/hexbin_pipeline/grid.py`, `pipeline/hexbin_pipeline/validate.py`
- Test: `pipeline/tests/test_validate.py`

- [ ] **Step 1: Extend the `staged` fixture in `pipeline/tests/test_validate.py`** — add one line next to the parcels.geojson stub:

```python
    (paths.work_dir(fips) / "county_boundary.geojson").write_text('{"type":"FeatureCollection","features":[]}')
```

And in `test_clean_run_publishes`, add:

```python
    assert (paths.processed_dir(staged) / "county_boundary.geojson").exists()
```

Add one new test:

```python
def test_missing_boundary_halts(staged):
    (paths.work_dir(staged) / "county_boundary.geojson").unlink()
    with pytest.raises(SystemExit):
        validate.run(staged)
```

Run: `.venv/Scripts/python.exe -m pytest pipeline/tests/test_validate.py -v` → the new/changed tests FAIL (boundary not gated/published yet). Report the red.

- [ ] **Step 2: `grid.py` — write the boundary in `run(fips)`**, after `gdf.to_parquet(dest)`:

```python
    boundary_path = grid_path(fips).parent / "county_boundary.geojson"
    county.to_crs("EPSG:4326")[["geometry"]].to_file(boundary_path, driver="GeoJSON")
    print(f"grid: wrote county boundary -> {boundary_path}")
```

- [ ] **Step 3: `validate.py` — gate + publish.** Extend the artifact loop:

```python
    bd_path = paths.work_dir(fips) / "county_boundary.geojson"
```
Add `bd_path` to the `for p in (xw_path, pq_path, gj_path):` tuple, and add a copy after the others:

```python
    shutil.copy2(bd_path, out / "county_boundary.geojson")
```

- [ ] **Step 4: Tests green + real run**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests -q          # expect 18 passed
.venv/Scripts/python.exe -m hexbin_pipeline grid --fips 54081
.venv/Scripts/python.exe -m hexbin_pipeline validate --fips 54081
ls -la data/processed/54081/county_boundary.geojson            # expect ~40-80 KB
```

- [ ] **Step 5: Commit**

```bash
git add pipeline/hexbin_pipeline/grid.py pipeline/hexbin_pipeline/validate.py pipeline/tests/test_validate.py
git commit -m "feat: publish county_boundary.geojson artifact (grid writes, validate gates)"
```

---

### Task 2: App config model (TDD)

**Files:**
- Modify: `app/src/types.ts`, `app/src/registry.ts`, `app/tests/registry.test.ts`, `app/src/db.ts`

- [ ] **Step 1: Add failing assertions** to the `builds defaults from the registry` test in `app/tests/registry.test.ts`:

```ts
    expect(cfg.basemap).toBe('none');
    expect(cfg.scoreOpacity).toBeCloseTo(0.8);
```
Run `cd app && npx vitest run tests/registry.test.ts` → FAIL (fields missing). Report red.

- [ ] **Step 2: `types.ts`** — add to `ScoringConfig`:

```ts
  basemap: 'none' | 'streets' | 'imagery'; // external Esri tiles; 'none' keeps the app offline
  scoreOpacity: number;                    // 0-1 alpha multiplier on the score layers
```

- [ ] **Step 3: `registry.ts` `defaultConfig`** — add `basemap: 'none',` and `scoreOpacity: 0.8,`.

- [ ] **Step 4: `db.ts`** — HEAD-check static files with the existing error style. Below the ARTIFACTS loop in `doInit`, add:

```ts
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
```

- [ ] **Step 5: Green + commit**

```bash
cd app && npx vitest run && npx tsc -b     # expect 15 passed (same count, richer assertions), clean
git add app/src/types.ts app/src/registry.ts app/tests/registry.test.ts app/src/db.ts
git commit -m "feat: basemap/scoreOpacity config fields and boundary artifact check"
```

---

### Task 3: Map chrome, base layers, header, panel cards

**Files:**
- Create: `app/src/components/MapControls.tsx`, `app/src/components/Legend.tsx`
- Modify: `app/src/components/MapView.tsx`, `app/src/components/WeightPanel.tsx`, `app/src/App.tsx`, `app/src/styles.css`

- [ ] **Step 1: `MapControls.tsx`**

```tsx
import type { ScoringConfig } from '../types';

const OPTIONS = ['none', 'streets', 'imagery'] as const;

interface Props {
  config: ScoringConfig;
  onChange: (cfg: ScoringConfig) => void;
}

export default function MapControls({ config, onChange }: Props) {
  return (
    <div className="map-card map-card-topright">
      <div className="seg">
        {OPTIONS.map((b) => (
          <button
            key={b}
            className={config.basemap === b ? 'seg-on' : ''}
            onClick={() => onChange({ ...config, basemap: b })}
          >
            {b}
          </button>
        ))}
      </div>
      <label className="opacity-row">
        scores {Math.round(config.scoreOpacity * 100)}%
        <input
          type="range" min={10} max={100} step={5}
          value={Math.round(config.scoreOpacity * 100)}
          onChange={(e) => onChange({ ...config, scoreOpacity: Number(e.target.value) / 100 })}
        />
      </label>
    </div>
  );
}
```

- [ ] **Step 2: `Legend.tsx`**

```tsx
import { RAMP } from './MapView';

export default function Legend() {
  return (
    <div className="map-card map-card-bottomleft legend">
      <span>low</span>
      {RAMP.map((c, i) => (
        <span key={i} className="swatch" style={{ background: `rgb(${c[0]},${c[1]},${c[2]})` }} />
      ))}
      <span>high</span>
      <span className="swatch" style={{ background: 'rgb(70,70,78)', marginLeft: 10 }} />
      <span>masked</span>
    </div>
  );
}
```

- [ ] **Step 3: `MapView.tsx` changes**

a. Export the ramp (change `const RAMP` to `export const RAMP`).
b. Imports: add `TileLayer` from `@deck.gl/geo-layers`, `BitmapLayer` from `@deck.gl/layers`.
c. Add above the component:

```tsx
const ESRI_BASE = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const TILE_URLS: Record<string, string[]> = {
  streets: [`${ESRI_BASE}/World_Street_Map/MapServer/tile/{z}/{y}/{x}`],
  imagery: [
    `${ESRI_BASE}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
    `${ESRI_BASE}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`,
  ],
};

function esriTileLayer(id: string, template: string) {
  return new TileLayer<ImageBitmap>({
    id, data: [template], maxZoom: 19, minZoom: 0, tileSize: 256,
    renderSubLayers: (props) => {
      const { west, south, east, north } = props.tile.bbox as {
        west: number; south: number; east: number; north: number };
      return new BitmapLayer(props, {
        data: undefined, image: props.data, bounds: [west, south, east, north] });
    },
  });
}
```

d. Alpha from config: replace the two `colorFor(...)` calls' default alpha by passing `Math.round(config.scoreOpacity * 255)` (hex layer scored cells AND masked-gray cells: masked gray becomes `[70, 70, 78, Math.round(config.scoreOpacity * 255)]`; parcel layer scored fill likewise, no-score fill stays as-is). Add `config.scoreOpacity` to both layers' `updateTriggers.getFillColor` arrays.

e. Build the final layer stack (replace the current `const layers = ...` result usage):

```tsx
  const baseLayers =
    config.basemap === 'none' ? [] : TILE_URLS[config.basemap].map((t, i) => esriTileLayer(`base-${config.basemap}-${i}`, t));
  const outline = new GeoJsonLayer({
    id: 'county-outline', data: '/county_boundary.geojson',
    stroked: true, filled: false, getLineColor: [255, 255, 255, 220],
    lineWidthMinPixels: 1.5, pickable: false,
  });
  const allLayers = [...baseLayers, ...layers, outline];
```
Pass `allLayers` to `<DeckGL layers={...}>`.

f. Mount the chrome inside `.map-wrap` (imports at top; MapView gains an `onChange` prop of type `(cfg: ScoringConfig) => void` added to `Props` and destructured):

```tsx
      <MapControls config={config} onChange={onChange} />
      <Legend />
```

- [ ] **Step 4: `App.tsx`** — pass `onChange={setConfig}` to `<MapView ... />`, and add the header as the first child of `.app` (error banner and busy indicator stay where they are, now visually below it):

```tsx
      <header className="app-header">
        <strong>WV Parcel Suitability</strong>
        <span className="muted">Raleigh County, WV (54081)</span>
        <span className="spacer" />
        <span className="muted">
          {hexRows.length.toLocaleString()} hexes · {parcelRows.length.toLocaleString()} parcels shown
        </span>
        {config.basemap !== 'none' && (
          <span className="muted attribution">Basemap: Esri, Maxar, Earthstar Geographics</span>
        )}
      </header>
```

- [ ] **Step 5: `WeightPanel.tsx`** — wrap each of the five sections in `<section className="panel-card"> ... </section>`: (1) the criteria groups loop AS A WHOLE stays split per group — wrap EACH group's `<div key={g}>` content card-style by changing it to `<section className="panel-card" key={g}>`; (2) Constraints (group title + mask rows); (3) Shortlist; (4) Scoring; (5) Display. The `group-title` divs become the card headers (styling handles it — no text changes).

- [ ] **Step 6: `styles.css`** — append:

```css
.app-header { display: flex; gap: 12px; align-items: baseline; padding: 6px 12px; background: #1c1f26; border-bottom: 1px solid #2a2e37; }
.app-header .spacer { flex: 1; }
.muted { color: #8a919e; font-size: 12px; }
.attribution { font-size: 11px; }
.panel-card { border: 1px solid #2a2e37; border-radius: 6px; padding: 8px 10px; margin-bottom: 10px; background: #20242c; }
.panel-card .group-title { margin: 0 0 6px; }
.map-card { position: absolute; z-index: 5; background: #1c1f26d9; border: 1px solid #3a4150; border-radius: 6px; padding: 6px 10px; backdrop-filter: blur(2px); }
.map-card-topright { top: 10px; right: 10px; display: flex; flex-direction: column; gap: 6px; }
.map-card-bottomleft { bottom: 10px; left: 10px; }
.seg { display: flex; }
.seg button { background: #2a2f3a; color: #d9dce1; border-radius: 0; padding: 3px 10px; text-transform: capitalize; }
.seg button:first-child { border-radius: 4px 0 0 4px; }
.seg button:last-child { border-radius: 0 4px 4px 0; }
.seg .seg-on { background: #2d6cdf; }
.opacity-row { display: flex; gap: 8px; align-items: center; font-size: 12px; }
.legend { display: flex; gap: 3px; align-items: center; font-size: 11px; }
.legend .swatch { width: 16px; height: 12px; display: inline-block; }
```

- [ ] **Step 7: Verify + commit**

```bash
cd app && npx vitest run && npx tsc -b && npx vite build 2>&1 | tail -3
git add app/src
git commit -m "feat: Esri basemaps, county outline, map chrome, header, panel cards"
```
tsc note: if `props.tile.bbox` typing fights the TileLayer generic, prefer a narrow `as` cast at that single site — do not loosen tsconfig.

---

### Task 4: Live verification + docs (controller-led)

- [ ] Controller drives Chrome: offline start with basemap none; switch streets → imagery (tiles load, labels overlay, attribution appears); opacity fade over imagery; legend + outline + header render; panel cards look right; no console errors; suite green.
- [ ] Append run-log line to `docs/data-sources.md`: `**2026-09-02 — UI polish: Esri basemaps, county outline artifact, map chrome.**`
- [ ] Commit docs, final light review, merge per finishing-a-development-branch.

## Out of scope
Vector basemaps/MapLibre, tile caching, scale bar, map-image export, table/scoring changes.
