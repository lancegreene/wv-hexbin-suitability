# Network Drive Time Implementation Plan (Phase B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `hwy_drive_min` pipeline measurement (network minutes from each cell to the nearest highway access point over the TIGER road graph of the county + adjacent counties), replacing the straight-line `roads` criterion in the registry with a classed "≤10 min" default the app renders, edits, and labels via Phase A machinery.

**Architecture:** Pure graph helpers (`measure/network.py`, TDD on synthetic hand-computed networks) under a thin measure module (`measure/hwy_access.py`). App side: `steps` becomes a valid REGISTRY-DEFAULT membership (moved into `membershipSQL`), an `effectiveSteps` resolver feeds drawer/labels/exports for default-steps criteria, and the golden fixture gains the new column with re-derived hand numbers. The registry swap + real county run land in one atomic task because `config/criteria.json` is shared by both sides.

**Tech Stack:** + `networkx>=3` (pure-Python, pipeline only). Branch: `drivetime`. Repo `hexbin`; pipeline `.venv/Scripts/python.exe`; app `cd app && npx ...`; ALL commands FOREGROUND with explicit timeouts.

**Reference:** spec `docs/superpowers/specs/2026-09-02-drive-time-design.md`.

**Ordering constraint (why Task 4 is atomic):** the app's registry loader and golden tests read the real `config/criteria.json`. Changing it before the app supports steps-defaults (Task 3) — or without updating the golden fixture in the same commit — breaks the suite. Tasks 1–3 are criteria.json-neutral.

---

## File structure

```
pipeline/pyproject.toml                       # + networkx
pipeline/hexbin_pipeline/fetch.py             # adjacent_geoids + adjacent-roads download
pipeline/hexbin_pipeline/measure/network.py   # NEW: SPEEDS, build_graph, find_access_points, node_minutes
pipeline/hexbin_pipeline/measure/hwy_access.py# NEW: measure module
pipeline/hexbin_pipeline/measure/__init__.py  # registry gains hwy_access (8 modules)
pipeline/hexbin_pipeline/validate.py          # known_extra += road_dist_m
pipeline/tests/test_fetch_adjacency.py        # NEW
pipeline/tests/test_network.py                # NEW
config/criteria.json                          # roads -> hwy_access (steps default, unit minutes)
app/src/types.ts                              # membership union += steps variant; unit += 'minutes'
app/src/registry.ts                           # validate steps defaults
app/src/scoring.ts                            # membershipSQL absorbs steps; effectiveMembershipSQL simplifies
app/src/steps.ts                              # effectiveSteps resolver
app/src/components/SettingsDrawer.tsx         # default-steps criteria: Classes active, no Curve option
app/src/components/{MapView,RankTable}.tsx    # labels via effectiveSteps
app/src/exports.ts                            # labels via effectiveSteps
app/tests/{registry,scoring,steps}.test.ts    # updates + re-derived golden numbers
```

Test baselines: pipeline 18 → 24; app 35 → 37 (counts in run steps are the contract).

---

### Task 1: Adjacent-county roads fetch (TDD on adjacency)

**Files:**
- Modify: `pipeline/hexbin_pipeline/fetch.py`
- Test: `pipeline/tests/test_fetch_adjacency.py`

- [ ] **Step 1: failing test `pipeline/tests/test_fetch_adjacency.py`**

```python
import geopandas as gpd
from shapely.geometry import box

from hexbin_pipeline.fetch import adjacent_geoids


def test_adjacent_geoids_finds_touching_counties_despite_sliver_gaps():
    # A(target) shares an edge with B; C is 50 m away (generalized-boundary
    # sliver); D is far. Buffer tolerance must catch C, exclude D.
    counties = gpd.GeoDataFrame({
        "GEOID": ["54081", "54019", "54045", "54001"],
        "geometry": [
            box(0, 0, 10_000, 10_000),
            box(10_000, 0, 20_000, 10_000),
            box(0, 10_050, 10_000, 20_000),
            box(50_000, 50_000, 60_000, 60_000),
        ],
    }, crs="EPSG:26917")
    assert adjacent_geoids(counties, "54081") == ["54019", "54045"]


def test_adjacent_geoids_missing_target_raises():
    counties = gpd.GeoDataFrame({"GEOID": ["54001"], "geometry": [box(0, 0, 1, 1)]},
                                crs="EPSG:26917")
    try:
        adjacent_geoids(counties, "54081")
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert "54081" in str(e)
```

Run `.venv/Scripts/python.exe -m pytest pipeline/tests/test_fetch_adjacency.py -v` → FAIL (no `adjacent_geoids`). Report red.

- [ ] **Step 2: implement in `fetch.py`** (near `load_county`):

```python
def adjacent_geoids(counties, fips, buffer_m=100):
    """GEOIDs of counties adjacent to `fips`, sliver-tolerant.

    Generalized boundary files leave small gaps between neighbors, so
    strict touches() misses real adjacency — buffer-and-intersect instead.
    `counties` must be in a metric CRS (caller reprojects).
    """
    target = counties[counties["GEOID"] == fips]
    if len(target) != 1:
        raise RuntimeError(f"adjacent_geoids: county {fips} not found in boundary file")
    zone = target.geometry.iloc[0].buffer(buffer_m)
    hits = counties[counties.geometry.intersects(zone) & (counties["GEOID"] != fips)]
    return sorted(hits["GEOID"].tolist())
```

And in `run(fips)`, right after the existing target-roads download:

```python
    import geopandas as gpd  # local, matches county_bounds' convention
    counties_m = gpd.read_file(raw_dir("county") / "counties.zip").to_crs("EPSG:26917")
    neighbors = adjacent_geoids(counties_m, fips)
    print(f"fetch: {len(neighbors)} adjacent counties for the road network: {neighbors}")
    for n in neighbors:
        download_file(ROADS_URL.format(fips=n), raw_dir("roads") / f"roads_{n}.zip")
```

- [ ] **Step 3: green + real fetch + commit**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests -q      # 20 passed
.venv/Scripts/python.exe -m hexbin_pipeline fetch --fips 54081   # timeout 600000
```
Expected: prints the neighbor list (Raleigh borders ~6: Boone, Fayette, Mercer, Summers, Wyoming — GEOIDs vary, just expect 5-7) and downloads their roads zips (a few MB each); everything else skips.

```bash
git add pipeline/hexbin_pipeline/fetch.py pipeline/tests/test_fetch_adjacency.py
git commit -m "feat: fetch adjacent-county roads for the drive-time network"
```

---

### Task 2: Network helpers (TDD, hand-computed synthetic graphs)

**Files:**
- Modify: `pipeline/pyproject.toml` (add `"networkx>=3",` to dependencies) then `.venv/Scripts/python.exe -m pip install -e pipeline` (timeout 300000)
- Create: `pipeline/hexbin_pipeline/measure/network.py`
- Test: `pipeline/tests/test_network.py`

- [ ] **Step 1: failing tests `pipeline/tests/test_network.py`**

Hand computations (1 mph = 26.8224 m/min):
- S1400 @30 mph → 804.672 m/min; 1000 m = **1.242742 min**
- S1630 @35 mph → 938.784 m/min; 1000 m = **1.065207 min**

```python
import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hexbin_pipeline.measure.network import build_graph, find_access_points, node_minutes

UTM = "EPSG:26917"


def roads_gdf(rows):
    return gpd.GeoDataFrame(
        {"MTFCC": [r[0] for r in rows]},
        geometry=[LineString(r[1]) for r in rows], crs=UTM)


BASE = [
    ("S1400", [(0, 0), (1000, 0)]),        # surface road A-B
    ("S1630", [(1000, 0), (2000, 0)]),     # ramp B-H
    ("S1100", [(2000, 0), (3000, 0)]),     # highway H-I
    ("S1400", [(9000, 9000), (9500, 9000)]),  # disconnected fragment
]


def test_access_point_is_ramp_end_touching_surface_road():
    access = find_access_points(roads_gdf(BASE))
    assert access == [(1000, 0)]  # B: ramp end on the surface road; H touches only S1100


def test_node_minutes_hand_computed():
    g, _ = build_graph(roads_gdf(BASE))
    minutes = node_minutes(g, [(1000, 0)])
    assert minutes[(1000, 0)] == pytest.approx(0.0)
    assert minutes[(0, 0)] == pytest.approx(1.242742, abs=1e-4)      # 1000 m @ 30 mph
    assert minutes[(2000, 0)] == pytest.approx(1.065207, abs=1e-4)   # 1000 m @ 35 mph
    assert (9000, 9000) not in minutes                                # unreachable fragment


def test_endpoint_snapping_connects_near_coincident_ends():
    rows = [
        ("S1400", [(0, 0), (1000.0004, 0.0003)]),  # rounds to (1000, 0)
        ("S1400", [(1000, 0), (2000, 0)]),
    ]
    g, _ = build_graph(roads_gdf(rows))
    minutes = node_minutes(g, [(2000, 0)])
    assert (0, 0) in minutes  # connected through the snapped shared endpoint


def test_no_access_points_is_loud():
    no_ramp = roads_gdf([("S1400", [(0, 0), (1000, 0)])])
    with pytest.raises(RuntimeError, match="access point"):
        find_access_points(no_ramp, strict=True)
```

Run → FAIL (no module). Report red.

- [ ] **Step 2: write `pipeline/hexbin_pipeline/measure/network.py`**

```python
"""Road-network graph helpers for the drive-time measurement.

TIGER lacks one-way/turn data, so the graph is undirected — standard for
screening-level accessibility. Endpoints are snapped to a 1 m grid so
segments that share an intersection connect despite float noise.
"""
import networkx as nx

MPH_TO_M_PER_MIN = 26.8224

# mph by TIGER MTFCC; editable. Unlisted classes get DEFAULT_MPH.
SPEEDS = {"S1100": 65, "S1200": 45, "S1400": 30, "S1500": 15,
          "S1630": 35, "S1640": 30}
DEFAULT_MPH = 25

SURFACE = {"S1200", "S1400", "S1500", "S1640"}  # roads you can be ON before a ramp


def _snap(coord):
    return (round(coord[0]), round(coord[1]))  # 1 m grid, metric CRS required


def build_graph(roads_m):
    """roads_m: GeoDataFrame of LineStrings in a metric CRS with MTFCC.

    Returns (graph, node_list). Edge weight = minutes at the class speed.
    Each LineString contributes one edge between its snapped endpoints,
    weighted by full geometric length (interior curvature counted).
    """
    g = nx.Graph()
    for mtfcc, geom in zip(roads_m["MTFCC"], roads_m.geometry):
        if geom is None or geom.is_empty:
            continue
        mph = SPEEDS.get(mtfcc, DEFAULT_MPH)
        coords = list(geom.coords)
        a, b = _snap(coords[0]), _snap(coords[-1])
        if a == b:
            continue  # degenerate loop after snapping
        minutes = geom.length / (mph * MPH_TO_M_PER_MIN)
        # keep the fastest edge if duplicate connections exist
        if not g.has_edge(a, b) or g[a][b]["minutes"] > minutes:
            g.add_edge(a, b, minutes=minutes)
    print(f"network: graph with {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
    return g, list(g.nodes)


def find_access_points(roads_m, strict=False):
    """Ramp (S1630) endpoints that touch a surface road — the bottom of the
    on-ramp, i.e. where the ordinary network reaches the highway system."""
    surface_ends = set()
    for mtfcc, geom in zip(roads_m["MTFCC"], roads_m.geometry):
        if mtfcc in SURFACE and geom is not None and not geom.is_empty:
            coords = list(geom.coords)
            surface_ends.add(_snap(coords[0]))
            surface_ends.add(_snap(coords[-1]))
    access = set()
    for mtfcc, geom in zip(roads_m["MTFCC"], roads_m.geometry):
        if mtfcc == "S1630" and geom is not None and not geom.is_empty:
            coords = list(geom.coords)
            for end in (_snap(coords[0]), _snap(coords[-1])):
                if end in surface_ends:
                    access.add(end)
    if not access and strict:
        raise RuntimeError("network: no highway access points found (no S1630 ramp "
                           "endpoint touches a surface road) — this county may have "
                           "no interchange, or the road extract is wrong")
    print(f"network: {len(access)} highway access points")
    return sorted(access)


def node_minutes(g, access_nodes):
    """Multi-source Dijkstra: minutes from every reachable node to the
    nearest access node. Unreachable nodes are absent from the result."""
    sources = [n for n in access_nodes if g.has_node(n)]
    if not sources:
        raise RuntimeError("network: no access node exists in the graph")
    return nx.multi_source_dijkstra_path_length(g, sources, weight="minutes")
```

- [ ] **Step 3: green + commit**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests -q   # 24 passed
git add pipeline/pyproject.toml pipeline/hexbin_pipeline/measure/network.py pipeline/tests/test_network.py
git commit -m "feat: road-network graph helpers with hand-verified drive times"
```

---

### Task 3: App support for registry-default steps (TDD; criteria.json untouched)

**Files:**
- Modify: `app/src/types.ts`, `app/src/registry.ts`, `app/src/scoring.ts`, `app/src/steps.ts`, `app/src/components/SettingsDrawer.tsx`, `app/src/components/MapView.tsx`, `app/src/components/RankTable.tsx`, `app/src/exports.ts`
- Test: `app/tests/registry.test.ts`, `app/tests/steps.test.ts`

- [ ] **Step 1: failing tests.** In `app/tests/registry.test.ts` add:

```ts
  it('accepts a registry-default steps membership and rejects an invalid one', () => {
    const mk = (steps: unknown) => ({
      criteria: [{ key: 'x', label: 'x', column: 'c', group: 'g', weight: 1,
        confidence: 'authoritative', unit: 'minutes',
        membership: { fn: 'steps', steps } as never }],
      masks: [],
    });
    expect(() => loadRegistry(mk([{ max: 10, score: 1, label: 'near' },
      { score: 0, label: 'far' }]))).not.toThrow();
    expect(() => loadRegistry(mk([{ max: 10, score: 1, label: 'near' }])))
      .toThrow(/invalid default classes for 'x'/);
  });
```

In `app/tests/steps.test.ts` add:

```ts
import { effectiveSteps } from '../src/steps';
// (plus type imports as needed)

describe('effectiveSteps', () => {
  const defSteps = [{ max: 10, score: 1, label: 'near' }, { score: 0, label: 'far' }];
  const curveCrit = { membership: { fn: 'small', midpoint: 1, spread: 1 } } as never;
  const stepsCrit = { membership: { fn: 'steps', steps: defSteps } } as never;
  it('override wins', () =>
    expect(effectiveSteps(stepsCrit, { mode: 'steps', steps: [{ score: 1, label: 'a' },
      { score: 0, label: 'b' }] })?.[0].label).toBe('a'));
  it('registry default steps apply when no override', () =>
    expect(effectiveSteps(stepsCrit, undefined)?.[0].label).toBe('near'));
  it('curve criterion without override has no steps', () =>
    expect(effectiveSteps(curveCrit, undefined)).toBeNull());
});
```

Run `cd app && npx vitest run` → the new tests FAIL. Report red.

- [ ] **Step 2: `types.ts`** — `MembershipFn` union gains `| { fn: 'steps'; steps: Step[] }`; `unit` union gains `'minutes'`. (Move/keep `Step` above `MembershipFn`.)

- [ ] **Step 3: `registry.ts`** — in `loadRegistry`'s criteria loop add:

```ts
    if (c.membership.fn === 'steps') {
      const errors = validateSteps(c.membership.steps);
      if (errors.length) {
        throw new Error(`criteria.json: invalid default classes for '${c.key}': ${errors.join('; ')}`);
      }
    }
```
(import `validateSteps` from `./steps`).

- [ ] **Step 4: `scoring.ts`** — move the steps SQL INTO `membershipSQL` as a `case 'steps':` branch (same CASE/ELSE construction; membershipSQL takes the steps from `m.steps`); `effectiveMembershipSQL` keeps its override branch (validated override → same construction via `membershipSQL({ fn: 'steps', steps: override.steps }, c.column)`) and otherwise calls `membershipSQL(c.membership, c.column)` — net effect: registry-default steps now work with zero call-site changes.

- [ ] **Step 5: `steps.ts`** — add the resolver:

```ts
import type { Criterion, NormalizationOverride } from './types';

/** The steps in effect for a criterion: override first, else registry default, else null. */
export function effectiveSteps(
  c: Pick<Criterion, 'membership'>,
  override: NormalizationOverride | undefined,
): Step[] | null {
  if (override?.mode === 'steps') return override.steps;
  if (override?.mode === 'curve') return null;
  if (c.membership.fn === 'steps') return c.membership.steps;
  return null;
}
```

- [ ] **Step 6: consumers.** In `MapView` tooltip, `RankTable` cells, and `exports.ts`'s `classProperties`, replace the `ov?.mode === 'steps' ? ov.steps : null` pattern with `effectiveSteps(criterion, config.normalization[key])` (each site already has the criterion or can look it up from the registry it holds). In `SettingsDrawer`: for a criterion whose registry default is steps, hide the Curve radio (there is no curve to fall back to), show Classes as active, seed the editor from `effectiveSteps`, and label the mode row "Classes (default)" when no override exists; "reset to default" behavior = removing the override (the existing Curve-radio handler renamed appropriately for this case is fine).

- [ ] **Step 7: green + commit**

```bash
cd app && npx vitest run && npx tsc -b && npx vite build 2>&1 | tail -2   # 39 passed
git add app/src app/tests
git commit -m "feat: registry-default step classes supported end to end"
```
(35 baseline + 1 registry + 3 steps = 39; the earlier "37" estimate in the header is superseded by this count — this line is the contract.)

---

### Task 4: The swap — criteria.json, hwy_access module, real run, golden re-derivation (atomic)

**Files:**
- Modify: `config/criteria.json`, `pipeline/hexbin_pipeline/measure/__init__.py`, `pipeline/hexbin_pipeline/validate.py`, `app/tests/scoring.test.ts`
- Create: `pipeline/hexbin_pipeline/measure/hwy_access.py`

- [ ] **Step 1: `config/criteria.json`** — replace the `roads` criterion entry with:

```json
    {"key": "hwy_access", "label": "Highway access", "column": "hwy_drive_min", "group": "Infrastructure",
     "unit": "minutes",
     "membership": {"fn": "steps", "steps": [
       {"max": 10, "score": 1.0, "label": "within 10 min"},
       {"score": 0.0, "label": "beyond 10 min"}]},
     "weight": 0.15, "confidence": "authoritative"},
```
Weights still sum to 1.0. Nothing else changes.

- [ ] **Step 2: `pipeline/hexbin_pipeline/measure/hwy_access.py`**

```python
import geopandas as gpd
import pandas as pd

from .. import paths
from ..fetch import adjacent_geoids
from .common import UTM
from .network import MPH_TO_M_PER_MIN, build_graph, find_access_points, node_minutes

ACCESS_LEG_MPH = 30  # centroid -> nearest graph node, straight line


def _load_roads(fips):
    counties_m = gpd.read_file(paths.raw_dir("county") / "counties.zip").to_crs(UTM)
    wanted = [fips] + adjacent_geoids(counties_m, fips)
    frames = []
    for f in wanted:
        p = paths.raw_dir("roads") / f"roads_{f}.zip"
        if not p.exists():
            raise RuntimeError(f"hwy_access: missing roads for county {f} ({p}) — "
                               f"run the fetch stage")
        frames.append(gpd.read_file(p)[["MTFCC", "geometry"]])
    roads = pd.concat(frames, ignore_index=True)
    print(f"hwy_access: {len(roads)} road segments across {len(wanted)} counties")
    return gpd.GeoDataFrame(roads, crs=frames[0].crs).to_crs(UTM)


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    roads_m = _load_roads(fips)
    graph, _ = build_graph(roads_m)
    access = find_access_points(roads_m, strict=True)
    minutes = node_minutes(graph, access)
    reachable_frac = len(minutes) / max(graph.number_of_nodes(), 1)
    print(f"hwy_access: {reachable_frac:.1%} of graph nodes reachable from access points")

    # ALL graph nodes, NaN minutes where unreachable: a centroid whose nearest
    # node sits on a disconnected fragment gets NULL (spec), never a silently
    # optimistic time from some farther reachable node
    all_nodes = list(graph.nodes)
    nodes = gpd.GeoDataFrame({"minutes": [minutes.get(n, float("nan")) for n in all_nodes]},
                             geometry=gpd.points_from_xy([n[0] for n in all_nodes],
                                                         [n[1] for n in all_nodes]),
                             crs=UTM)
    cents = cells.to_crs(UTM)[["h3_index", "geometry"]].copy()
    cents["geometry"] = cents.geometry.centroid
    joined = gpd.sjoin_nearest(cents, nodes, distance_col="leg_m").drop_duplicates("h3_index")
    drive_min = (joined["minutes"] + joined["leg_m"] / (ACCESS_LEG_MPH * MPH_TO_M_PER_MIN))
    out = pd.DataFrame({"h3_index": joined["h3_index"].values,
                        "hwy_drive_min": drive_min.values})
    out = out.set_index("h3_index").reindex(cells["h3_index"]).reset_index()
    n_null = int(out["hwy_drive_min"].isna().sum())
    if n_null:
        print(f"hwy_access: WARNING — {n_null}/{len(out)} cells unreachable (NULL); "
              f"validate gates on the null rate")
    dest = paths.work_dir(fips) / "measure_hwy_access.parquet"
    out.to_parquet(dest, index=False)
    print(f"hwy_access: wrote {len(out)} rows, median {out.hwy_drive_min.median():.1f} min, "
          f"max {out.hwy_drive_min.max():.1f} min -> {dest}")
    return dest
```

Note: the nodes frame carries every graph node with NaN for unreachable
ones, so a centroid whose nearest node is on a disconnected fragment
yields NULL — surfaced by the module's WARNING count and gated by
validate's 1% null threshold, exactly per spec.

- [ ] **Step 3: wire up.** `measure/__init__.py`: import + register `"hwy_access": hwy_access` (8 modules; keep `roads` registered — `road_dist_m` remains a published measurement). `validate.py`: `known_extra` gains `"road_dist_m"`.

- [ ] **Step 4: golden fixture re-derivation, `app/tests/scoring.test.ts`.** New default criteria (slope .2, flood .15, water .2, **hwy_access .15**, transmission .15, landcover .15):
  - FIXTURE cells table: replace the `road_dist_m` column values (keep the column! it is measured data) AND add `hwy_drive_min`: cell a **10.0**, b **10.0**, c **25.0** (10.0 proves the ≤10 boundary inclusive via the registry default).
  - Hand numbers: cell a memberships — slope .5, flood 1, water 1, hwy 1.0, transmission .5, landcover 1 → **WLC = .2·.5+.15·1+.2·1+.15·1+.15·.5+.15·1 = 0.825**. Geometric = exp(.2·ln.5 + .15·ln.5) = 0.5^0.35 = **0.784584**.
  - Update every assertion that referenced 0.75/0.375/0.65/√½/`m_roads`:
    `hand-computed scores match` → a 0.825; parcel P1 0.825, P2 = .8·.825 = **0.66**, masked_frac 0.2 unchanged; doubling-weights → 0.825; geometric → 0.784584 (use `toBeCloseTo(0.784584, 4)`); the roads-steps inclusivity test becomes a hwy default-steps test: `m_hwy_access` for cell a (10.0 min) with NO override must be 1.0; the slope-override test: WLC with slope→0 = 0.825 − .2·.5 = **0.725**.
  - min-acres tests unchanged (parcel set unchanged).

- [ ] **Step 5: full suites**

```bash
cd app && npx vitest run && npx tsc -b     # 39 passed (assertions changed, count unchanged... verify — if the inclusivity rewrite split into 2 its, adjust and report the count you got with reasoning)
cd .. && .venv/Scripts/python.exe -m pytest pipeline/tests -q   # 24 passed
```

- [ ] **Step 6: real run** (foreground; measure timeout 600000):

```bash
.venv/Scripts/python.exe -m hexbin_pipeline measure --fips 54081 --only hwy_access
.venv/Scripts/python.exe -m hexbin_pipeline validate --fips 54081
```
Expected: segment count across ~7 counties (order 40–80k), access-point count order 10–60, reachable fraction > 95%, median drive 5–25 min, `validate: OK — 118972 cells, 15 columns`. STOP + report on: zero access points, reachable < 90%, median outside 2–40 min, or any validate failure. Do NOT weaken gates.

- [ ] **Step 7: commit**

```bash
git add config/criteria.json pipeline/hexbin_pipeline/measure/hwy_access.py pipeline/hexbin_pipeline/measure/__init__.py pipeline/hexbin_pipeline/validate.py app/tests/scoring.test.ts
git commit -m "feat: hwy_access drive-time measurement replaces roads criterion"
```

---

### Task 5: Live verification + docs (controller-led)

- [ ] Controller drives Chrome: "Highway access" slider present with badgeless authoritative label; drawer shows it in Classes (default) mode with the ≤10 min tier, Curve hidden; map/table re-rank sensibly (Beckley corridor high); tooltip shows "within 10 min"/"beyond 10 min"; an old Phase A preset loads with hwy_access filled from defaults (reconcile); CSV gains `hwy_access_class`.
- [ ] Run-log entry in `docs/data-sources.md` (access-point count, median/max minutes, reachable %, the nearest-reachable-node caveat).
- [ ] Commit docs; final whole-branch review (this feature crosses pipeline+registry+app — dispatch the integration reviewer); merge per finishing-a-development-branch.

## Out of scope
One-ways/turn restrictions, congestion, other destination sets, per-county speed calibration, multi-county display.
