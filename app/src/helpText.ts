/** All section-help wording in one place. Keep entries to tooltip length. */
export const HELP: Record<string, string> = {
  weights:
    'Each slider is a weight in the scoring average. Weights are normalized ' +
    'before scoring, so only their ratios matter — doubling every slider ' +
    'changes nothing. Each criterion is first converted to a 0–1 score ' +
    '(via its curve or classes), then combined using these weights.',
  constraints:
    'Hard masks multiply a cell’s score by zero — floodway, undermined, or ' +
    'too-steep land scores nothing no matter how good everything else is. ' +
    'Unlike weights, masks are non-negotiable: nothing compensates. ' +
    'Masked area shows gray on the hex map.',
  shortlist:
    'Filters the ranked table and exports to parcels at or above this ' +
    'acreage. Without it, tiny urban lots dominate the top of the list ' +
    '(they sit entirely inside ideal cells). Scores are unaffected — this ' +
    'only filters which parcels are listed.',
  scoring:
    'Weighted sum lets strengths offset weaknesses (fully compensatory): a ' +
    'parcel with no water can still rank high if everything else is ideal. ' +
    'Geometric multiplies instead — being bad at any one criterion drags ' +
    'the score down hard (a soft veto). Tip: rank with weighted sum, then ' +
    'flip to geometric as an audit — parcels that plummet have one hidden ' +
    'weak leg worth checking.',
  display:
    'Hex resolution trades detail for speed of reading: res 8 averages ' +
    '~49 cells per hex for screening; res 10 is the full measurement grid. ' +
    'Parcel view colors every parcel by its own score (first switch ' +
    'tessellates 60k polygons — ~30 s). All views re-rank live.',
  normalization:
    'How raw measurements become 0–1 scores. A curve falls smoothly ' +
    '(0.5 at its midpoint) — no hard cutoffs. Classes are your tiers: ' +
    'each bound gets a score and a plain-English label that appears in ' +
    'tooltips, the table, and exports. Bounds are inclusive (exactly at ' +
    'the bound lands inside that class).',
  presets:
    'A preset saves the entire setup — weights, masks, classes, filters. ' +
    'Everything also autosaves in this browser; presets add named ' +
    'scenarios ("industrial", "solar") you can reload, export as a JSON ' +
    'file to share or commit, and import on another machine.',
};
