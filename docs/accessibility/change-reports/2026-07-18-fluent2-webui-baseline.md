# Local Web UI WCAG-EM Evaluation Report

> Superseded evidence: this report is retained as historical context only. It is
> not bound to the final Fluent React assets, and later review found blocking
> defects; use `2026-07-18-fluent-ui-react-v9-migration.md` for the replacement.

Evidence kind: `Material base-component change`
Identifier: `2026-07-18-fluent2-webui-baseline`
Evaluated revision: base `743e4d9f9d3e2219385d70f7b4c84a7b78cb5f4c` with
Local Web UI asset SHA-256
`8a32c6a474dfbc62813217248431664854bdb89954bbeae9e5f17b1159859d21`
Evaluator: Project owner, reported through the Codex task
Date: `2026-07-18`
Result: Fail

## Scope and sample

- Navigation Entries: Home, Timeline, Catalog, Lists, Insights, Data Operations,
  and Settings.
- Important states: loading, empty/populated data, language and theme changes,
  Timeline order/review controls, validation errors, operation failures, and
  Windows forced-colors emulation.
- Exclusions and rationale: OBS Overlay is a separate viewer-facing surface under
  ADR 0009.

## Environment

- Windows: Windows environment; exact build was not recorded.
- Browser and version: Not recorded.
- Display scale and browser zoom: Coarse manual check reported; exact values were
  not recorded.
- Keyboard/input devices: Coarse keyboard check reported; device details were not
  recorded.
- Screen reader and version: Coarse screen-reader check reported; product and
  version were not recorded.
- Windows Contrast Themes: Coarse high-contrast check reported; selected themes
  were not recorded.

## Automated prerequisite

- `pnpm test:a11y` result: Pass, 30/30 tests on 2026-07-18; all seven
  Navigation Entries passed light/dark axe scans with zero detected violations.
- Python regression suite: Pass, 258/258 tests on 2026-07-18.
- CI run: Pending.

## Manual results

### Keyboard and focus

- Result: Not run (advisory); the earlier coarse observation was not retained.
- Evidence/findings: No blocking keyboard, focus-order, focus-visibility, or trap
  issue was reported. Detailed key-by-key observations were not retained.

### Screen reader

- Result: Not run (advisory); the earlier coarse observation was not retained.
- Evidence/findings: No blocking landmark, accessible-name, state, table, live
  region, validation, or language issue was reported. Assistive-technology
  details and observation notes were not retained.

### Zoom, reflow, and text spacing

- Result: Not run (advisory); the earlier coarse observation was not retained.
- Evidence/findings: No blocking loss, overlap, clipping, or page-level
  horizontal overflow was reported. Exact zoom and text-spacing observations
  were not retained; the automated 320 CSS-pixel Timeline regression also passed.

### Light, dark, system, and Windows high contrast

- Result: Not run (advisory); the earlier coarse observation was not retained.
- Evidence/findings: No blocking theme, focus, border, state, or color-only issue
  was reported. Exact Windows Contrast Theme names were not retained; browser
  forced-colors automation also passed.

## Open issues

- Later review found blocking pressed-state contrast and short-viewport focus
  visibility failures in this superseded implementation.
- Historical evidence limitation: browser, assistive-technology, display, and
  Contrast Theme versions plus step-by-step observations were not retained.
  These optional observations are not the reason the report fails.

## Conclusion

The historical asset is not the final Fluent React bundle, and later review
found blocking failures in it. This report is therefore `Result: Fail` and must
not be used as merge, release, or WCAG-conformance evidence. Optional manual
review is not the reason for this failure.
