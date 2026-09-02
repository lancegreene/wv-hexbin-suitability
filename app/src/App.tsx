import { cellToLatLng } from 'h3-js';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import MapView, { type ViewTarget } from './components/MapView';
import RankTable from './components/RankTable';
import SettingsDrawer from './components/SettingsDrawer';
import WeightPanel from './components/WeightPanel';
import { initDB, query } from './db';
import { exportCSV, exportGeoJSON } from './exports';
import { loadCurrent, saveCurrent } from './persistence';
import { loadRegistry } from './registry';
import { buildHexAggSQL, buildParcelScoreSQL } from './scoring';
import { validateSteps } from './steps';
import type { ScoringConfig } from './types';

const registry = loadRegistry();

type Phase = { state: 'loading'; msg: string } | { state: 'error'; msg: string } | { state: 'ready' };

export default function App() {
  const [phase, setPhase] = useState<Phase>({ state: 'loading', msg: 'Starting DuckDB…' });
  const [queryError, setQueryError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<ScoringConfig>(() => loadCurrent(registry));
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [hexRows, setHexRows] = useState<Record<string, unknown>[]>([]);
  const [parcelRows, setParcelRows] = useState<Record<string, unknown>[]>([]);
  const [parcelsGeojson, setParcelsGeojson] = useState<unknown | null>(null);
  const [viewTarget, setViewTarget] = useState<ViewTarget>({ longitude: -81.2, latitude: 37.75, zoom: 9 });
  const debounceRef = useRef<number>(0);

  useEffect(() => {
    const t = window.setTimeout(() => saveCurrent(config), 300);
    return () => window.clearTimeout(t);
  }, [config]);

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
      setBusy(true);
      try {
        const t0 = performance.now();
        const [hex, parcels] = await Promise.all([
          query(buildHexAggSQL(registry, cfg)),
          query(buildParcelScoreSQL(registry, cfg)),
        ]);
        setHexRows(hex);
        setParcelRows(parcels);
        setQueryError(null);
        console.log(`rescore: ${(performance.now() - t0).toFixed(0)} ms ` +
          `(${hex.length} hexes, ${parcels.length} parcels)`);
      } catch (e) {
        // Non-terminal: keep the panel usable so the user can recover
        setQueryError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    }, 60);
  }, []);

  const totalWeight = Object.values(config.weights).reduce((s, w) => s + w, 0);

  const stepsValid = Object.entries(config.normalization).every(
    ([, ov]) => ov.mode !== 'steps' || validateSteps(ov.steps).length === 0);
  useEffect(() => {
    if (phase.state === 'ready' && totalWeight > 0 && stepsValid) rescore(config);
  }, [phase.state, config, rescore, totalWeight, stepsValid]);

  const parcelScores = useMemo(
    () => new Map(parcelRows.map((r) => [String(r.parcel_id), r])),
    [parcelRows],
  );

  if (phase.state === 'loading') return <div className="loading">{phase.msg}</div>;
  if (phase.state === 'error') return <div className="error-screen">{phase.msg}</div>;

  return (
    <div className="app">
      <header className="app-header">
        <strong>WV Parcel Suitability</strong>
        <span className="muted">Raleigh County, WV (54081)</span>
        <span className="spacer" />
        <span className="muted">
          {hexRows.length.toLocaleString()} hexes · {parcelRows.length.toLocaleString()} parcels shown
        </span>
        <button className="secondary" onClick={() => setSettingsOpen((v) => !v)}>⚙ settings</button>
        {config.basemap !== 'none' && (
          <span className="muted attribution">Basemap: Esri, Maxar, Earthstar Geographics</span>
        )}
      </header>
      {queryError && (
        <div className="query-error-banner">
          scoring failed: {queryError}
          <button className="secondary" onClick={() => setQueryError(null)}>dismiss</button>
        </div>
      )}
      {busy && <div className="busy-indicator">scoring…</div>}
      <div className="app-main">
        <WeightPanel registry={registry} config={config} onChange={setConfig} />
        {totalWeight > 0 ? (
          <MapView config={config} registry={registry} hexRows={hexRows}
            parcelScores={parcelScores} parcelsGeojson={parcelsGeojson} viewTarget={viewTarget}
            onChange={setConfig} />
        ) : (
          <div className="map-wrap loading">All weights are zero — raise at least one slider.</div>
        )}
        {settingsOpen && (
          <SettingsDrawer registry={registry} config={config} onChange={setConfig}
            onClose={() => setSettingsOpen(false)} />
        )}
      </div>
      <RankTable registry={registry} config={config} rows={parcelRows}
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
        onExportCSV={() => exportCSV(parcelRows, registry, config)}
        onExportGeoJSON={() => parcelsGeojson &&
          exportGeoJSON(parcelRows, parcelsGeojson as never, config)}
      />
    </div>
  );
}
