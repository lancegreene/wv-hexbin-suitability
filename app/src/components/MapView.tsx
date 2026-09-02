import { GeoJsonLayer } from '@deck.gl/layers';
import { H3HexagonLayer } from '@deck.gl/geo-layers';
import DeckGL from '@deck.gl/react';
import { useEffect, useState } from 'react';
import type { Registry, ScoringConfig } from '../types';

// Viridis-ish 6-stop ramp, low -> high suitability
const RAMP: [number, number, number][] = [
  [68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37], [255, 255, 200],
];
function colorFor(score: number, alpha = 200): [number, number, number, number] {
  // NaN-safe: a bad score renders as lowest-suitability instead of throwing
  // a per-feature TypeError across 60k parcels
  const t = Number.isFinite(score) ? Math.max(0, Math.min(0.999, score)) : 0;
  const [r, g, b] = RAMP[Math.floor(t * RAMP.length)];
  return [r, g, b, alpha];
}

export interface ViewTarget { longitude: number; latitude: number; zoom: number }

interface Props {
  config: ScoringConfig;
  registry: Registry;
  hexRows: Record<string, unknown>[];
  parcelScores: Map<string, Record<string, unknown>>;
  parcelsGeojson: unknown | null;
  viewTarget: ViewTarget;
}

export default function MapView({ config, registry, hexRows, parcelScores, parcelsGeojson, viewTarget }: Props) {
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

  const layers = config.displayMode === 'hex' || !parcelWarm
    ? [new H3HexagonLayer({
        id: `hex-${config.resolution}`,
        data: hexRows,
        getHexagon: (d: Record<string, unknown>) => String(d.h3),
        getFillColor: (d: Record<string, unknown>) =>
          Number(d.mask_factor) === 0 ? [70, 70, 78, 160] : colorFor(Number(d.score)),
        extruded: false, stroked: false, pickable: true,
        updateTriggers: { getFillColor: [hexRows] },
      })]
    : [new GeoJsonLayer({
        id: 'parcels',
        data: parcelsGeojson as never,
        getFillColor: (f: { properties: { parcel_id: string } }) => {
          const row = parcelScores.get(f.properties.parcel_id);
          return row ? colorFor(Number(row.score)) : [40, 40, 46, 120];
        },
        getLineColor: [20, 20, 24, 255], lineWidthMinPixels: 0.3,
        pickable: true,
        updateTriggers: { getFillColor: [parcelScores] },
      })];

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
        layers={layers}
        getTooltip={({ object }: { object?: Record<string, unknown> }) => {
          if (!object) return null;
          const row = 'properties' in object
            ? parcelScores.get(String((object.properties as { parcel_id: string }).parcel_id))
            : object;
          if (!row) return null;
          const breakdown = registry.criteria
            .map((c) => `${c.label}: ${Number(row[`m_${c.key}`]).toFixed(2)}`)
            .join('\n');
          return { text: `score ${Number(row.score).toFixed(3)}\n${breakdown}` };
        }}
      />
    </div>
  );
}
