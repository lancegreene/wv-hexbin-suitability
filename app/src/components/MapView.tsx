import { GeoJsonLayer, BitmapLayer } from '@deck.gl/layers';
import { H3HexagonLayer, TileLayer } from '@deck.gl/geo-layers';
import DeckGL from '@deck.gl/react';
import { useEffect, useState } from 'react';
import MapControls from './MapControls';
import Legend from './Legend';
import { labelForScore } from '../steps';
import type { Registry, ScoringConfig } from '../types';

// Viridis-ish 6-stop ramp, low -> high suitability
export const RAMP: [number, number, number][] = [
  [68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37], [255, 255, 200],
];
function colorFor(score: number, alpha = 200): [number, number, number, number] {
  // NaN-safe: a bad score renders as lowest-suitability instead of throwing
  // a per-feature TypeError across 60k parcels
  const t = Number.isFinite(score) ? Math.max(0, Math.min(0.999, score)) : 0;
  const [r, g, b] = RAMP[Math.floor(t * RAMP.length)];
  return [r, g, b, alpha];
}

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
      return new BitmapLayer(props as never, {
        data: undefined, image: props.data, bounds: [west, south, east, north] });
    },
  });
}

export interface ViewTarget { longitude: number; latitude: number; zoom: number }

interface Props {
  config: ScoringConfig;
  registry: Registry;
  hexRows: Record<string, unknown>[];
  parcelScores: Map<string, Record<string, unknown>>;
  parcelsGeojson: unknown | null;
  viewTarget: ViewTarget;
  onChange: (cfg: ScoringConfig) => void;
}

export default function MapView({ config, registry, hexRows, parcelScores, parcelsGeojson, viewTarget, onChange }: Props) {
  // First switch to parcel mode tessellates 60k polygons (~30 s, blocks the
  // main thread). Paint the notice FIRST, then construct the layer on a later
  // frame — a layer built in the same render would freeze before the notice
  // ever appears.
  const [parcelWarm, setParcelWarm] = useState(false);
  const wantParcels = config.displayMode === 'parcel';
  useEffect(() => {
    if (wantParcels && !parcelWarm) {
      const t = window.setTimeout(() => setParcelWarm(true), 50);
      return () => window.clearTimeout(t);
    }
  }, [wantParcels, parcelWarm]);

  const scoreAlpha = Math.round(config.scoreOpacity * 255);

  const layers = config.displayMode === 'hex' || !parcelWarm
    ? [new H3HexagonLayer({
        id: `hex-${config.resolution}`,
        data: hexRows,
        getHexagon: (d: Record<string, unknown>) => String(d.h3),
        getFillColor: (d: Record<string, unknown>) =>
          Number(d.mask_factor) === 0 ? [70, 70, 78, scoreAlpha] : colorFor(Number(d.score), scoreAlpha),
        extruded: false, stroked: false, pickable: true,
        updateTriggers: { getFillColor: [hexRows, config.scoreOpacity] },
      })]
    : [new GeoJsonLayer({
        id: 'parcels',
        data: parcelsGeojson as never,
        getFillColor: (f: { properties: { parcel_id: string } }) => {
          const row = parcelScores.get(f.properties.parcel_id);
          return row ? colorFor(Number(row.score), scoreAlpha) : [40, 40, 46, 120];
        },
        getLineColor: [20, 20, 24, 255], lineWidthMinPixels: 0.3,
        pickable: true,
        updateTriggers: { getFillColor: [parcelScores, config.scoreOpacity] },
      })];

  const baseLayers =
    config.basemap === 'none' ? [] : TILE_URLS[config.basemap].map((t, i) => esriTileLayer(`base-${config.basemap}-${i}`, t));
  const outline = new GeoJsonLayer({
    id: 'county-outline', data: '/county_boundary.geojson',
    stroked: true, filled: false, getLineColor: [255, 255, 255, 220],
    lineWidthMinPixels: 1.5, pickable: false,
  });
  const allLayers = [...baseLayers, ...layers, outline];

  return (
    <div className="map-wrap">
      {wantParcels && !parcelWarm && (
        <div className="parcel-warmup">
          rendering 60,683 parcels — the first switch takes ~30 s…
        </div>
      )}
      <DeckGL
        initialViewState={{ ...viewTarget, pitch: 0, bearing: 0 }}
        controller
        layers={allLayers}
        getTooltip={({ object }: { object?: Record<string, unknown> }) => {
          if (!object) return null;
          const row = 'properties' in object
            ? parcelScores.get(String((object.properties as { parcel_id: string }).parcel_id))
            : object;
          if (!row) return null;
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
          return { text: `score ${Number(row.score).toFixed(3)}\n${breakdown}` };
        }}
      />
      <MapControls config={config} onChange={onChange} />
      <Legend />
    </div>
  );
}
