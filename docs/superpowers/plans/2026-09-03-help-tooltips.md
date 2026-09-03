# Section Help Tooltips Implementation Plan

> Executed inline (single small task) per user approval — ~80 lines, no
> behavior changes.

**Goal:** ⓘ hover/focus tooltips explaining each control section's math.

### Task 1 (only task)
- [ ] Create `app/src/helpText.ts` (HELP map) and `app/src/components/Help.tsx`.
- [ ] Mount in `WeightPanel.tsx` (group headers, Constraints, Shortlist,
      Scoring, Display) and `SettingsDrawer.tsx` (mode rows, Presets).
- [ ] Tooltip CSS in `styles.css` (`.help-icon`, `.help-tip`).
- [ ] `cd app && npx vitest run && npx tsc -b && npx vite build` → 40
      passed, clean. Live Chrome hover check. Commit.
