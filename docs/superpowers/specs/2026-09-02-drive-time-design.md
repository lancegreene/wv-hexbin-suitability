# Network Drive Time to Highway Access (Phase B) — Design

2026-09-02. Phase B of the classed-scoring feature: a true network
drive-time measurement, consumed by Phase A's classing like any other
column. User explicitly chose real network time over distance
approximation, destination = highway access points.

## Decisions

| Question | Decision |
|---|---|
| Measurement | `hwy_drive_min` — minutes of network drive time from each res-10 cell centroid to the nearest highway access point |
| Destinations | Highway access points derived from TIGER: endpoints of ramp segments (MTFCC S1630) that touch a surface road (non-ramp, non-S1100) — i.e., where you can get onto the limited-access system |
| Network | TIGER roads for the county PLUS all adjacent counties (routes near the boundary legitimately leave the county; adjacency computed from the counties file; ~6 extra small downloads) |
| Speeds | mph by MTFCC, editable constants: S1100 65, S1200 45, S1400 30, S1500 15, S1630 35, S1640 30, other 25 |
| Algorithm | One multi-source Dijkstra from all access points over the edge-weighted graph (networkx, new pipeline dep `networkx>=3` — pure Python); cell time = time at nearest graph node + centroid→node straight-line leg at 30 mph |
| Unreachable cells | NULL + loud printed count (disconnected TIGER fragments); validate's 1% null gate is the backstop; the module also prints the % of graph nodes reachable from access points |
| Registry default | **`hwy_access` REPLACES the `roads` criterion** in `config/criteria.json` (weight 0.15, group Infrastructure, unit `minutes`), with a classed default matching the user's ask: ≤10 min → 1.0 "within 10 min", above → 0.0 "beyond 10 min". `road_dist_m` stays measured and published (added to validate's known-extra list) so a roads-distance criterion can be re-added anytime. |
| Registry membership | `steps` becomes a valid REGISTRY default membership (the union gains it; `membershipSQL` absorbs the steps SQL now living in `effectiveMembershipSQL`) — Phase A runtime overrides are unchanged |

## Pipeline changes

- **fetch:** adjacent counties = counties whose geometry touches the
  target county (from the cached national boundary file); download each
  adjacent `tl_2024_<fips>_roads.zip` into the shared `data/raw/roads/`
  cache (skip-if-present; same loud-failure rules).
- **new measure module `hwy_access.py`:**
  1. Load target + adjacent county roads; build an undirected graph:
     nodes = segment endpoints (coords rounded to 1 m in EPSG:26917 so
     shared endpoints snap), edge weight = minutes
     (`length_m / (mph · 26.8224)`).
  2. Detect access points (ramp-endpoint rule above). Zero access points
     → RuntimeError naming the county (a county with no interchange is
     possible — that is a real finding, not a silent zero).
  3. Multi-source Dijkstra from all access nodes → minutes per node.
  4. Map each cell centroid to its nearest graph node (sindex.nearest);
     `hwy_drive_min` = node minutes + access leg at 30 mph. Print
     median/max and the unreachable-cell count.
  5. Write `measure_hwy_access.parquet`. Cache the per-node times table
     in `data/work/<fips>/` so re-runs skip the Dijkstra when roads are
     unchanged? NO — the graph build is expected to be < 2 min; keep it
     simple and recompute (matches other modules; no cache-invalidation
     surface).
- **registry/validate:** `hwy_drive_min` joins via criteria.json
  automatically; `road_dist_m` moves to validate's known-extra set.
- Run for 54081: fetch (adjacent roads) → `measure --only hwy_access` →
  `validate`. No other module re-runs.

## App changes (small)

- `unit` union gains `"minutes"` (identity display, suffix "min").
- Registry `Criterion.membership` union gains the steps variant;
  `loadRegistry` validates registry-default steps with the same
  `validateSteps`; `membershipSQL` handles steps directly (moved from
  `effectiveMembershipSQL`, which now only resolves override-vs-default).
- The drawer already renders steps for any criterion — a registry-default
  steps criterion opens in Classes mode with its default tiers, Curve
  mode disabled when the registry default IS steps (no curve to fall
  back to).
- Golden-test fixture gains a `hwy_drive_min` column; hand computations
  re-derived for the new default criteria set (hand numbers in the plan
  are the contract).

## Sanity expectations (Raleigh 54081)

I-77 and I-64 cross the county with multiple interchanges: expect a
nonzero access-point count (order 10–40), median drive time plausibly
5–25 min, Beckley-area cells low, remote hollows 30–60+. All-zero or
all-null results must halt, never publish.

## Testing

- Pipeline (pytest, TDD): synthetic cross-shaped network with known
  speeds → hand-computed node minutes; ramp-endpoint access detection on
  a synthetic 3-class network; endpoint snapping (two segments sharing a
  rounded endpoint connect); unreachable-fragment produces NULL not 0.
- App: registry-default steps validation + golden with the new fixture
  column; drawer Curve-disabled state.
- Live: full pipeline run for 54081, map/table check with the new
  criterion, preset reconciliation (Phase A presets load with the new
  criterion filled from defaults — already guaranteed by `reconcile`).

## Out of scope

Turn restrictions/one-ways (TIGER lacks them; undirected is standard for
this class of screening), congestion/time-of-day, non-highway
destinations (rail, airports), multi-county app display.
