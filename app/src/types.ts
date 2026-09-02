export interface Step {
  max?: number;  // inclusive upper bound in the column's stored unit; absent = catch-all (must be last)
  score: number; // 0-1
  label: string; // plain-English class meaning, surfaces in tooltip/table/CSV
}

export type MembershipFn =
  | { fn: 'small'; midpoint: number; spread: number }
  | { fn: 'binary' }
  | { fn: 'lookup'; miss_score: number; table: Record<string, number> }
  | { fn: 'steps'; steps: Step[] };

export interface Criterion {
  key: string;
  label: string;
  column: string;
  group: string;
  membership: MembershipFn;
  weight: number;
  confidence: string;
  confidence_column?: string;
  unit: 'pct_slope' | 'pct' | 'meters' | 'binary' | 'category' | 'minutes';
}

export type NormalizationOverride =
  | { mode: 'curve' }
  | { mode: 'steps'; steps: Step[] };

export interface Mask {
  key: string;
  label: string;
  column: string;
  predicate: string; // "> 0" or "> {threshold}"
  default_threshold?: number;
}

export interface Registry {
  criteria: Criterion[];
  masks: Mask[];
}

export interface ScoringConfig {
  weights: Record<string, number>;        // criterion key -> raw weight (unnormalized)
  masksEnabled: Record<string, boolean>;  // mask key -> on/off
  slopeThreshold: number;                 // fills {threshold}
  minAcres: number;                       // shortlist filter: parcels below this are excluded
  aggregation: 'wlc' | 'geometric';
  resolution: 8 | 9 | 10;
  displayMode: 'hex' | 'parcel';
  basemap: 'none' | 'streets' | 'imagery'; // external Esri tiles; 'none' keeps the app offline
  scoreOpacity: number;                    // 0-1 alpha multiplier on the score layers
  normalization: Record<string, NormalizationOverride>;
}
