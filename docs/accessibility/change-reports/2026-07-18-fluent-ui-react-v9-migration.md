# Local Web UI Accessibility Evaluation Report

Evidence kind: `Material base-component change`
Identifier: `2026-07-18-fluent-ui-react-v9-migration`
Evaluated revision: `4085e23b10c0719de6ea8f0df4177ae1de9dbe6a`
Asset SHA-256 (`dancing_log/webui_dist/app.js`): `8fc83a3b6406942843edc841be602fa2c3f9aec7f2508b8fb9effa5ce20bc166`
Asset SHA-256 (`dancing_log/webui_dist/index.html`): `88c368311d9d2d509aa3cc272ead59006d9cddc1687f3a81114adb4c63957d11`
Evaluator: Automated checks run through the Codex task
Date: `2026-07-18`
Result: Pass

## Scope and sample

- Navigation Entries: Home, Timeline, Catalog, Lists, Insights, Data Operations,
  and Settings.
- Important states: loading, empty/populated data, language and official Fluent
  Web Theme changes, Timeline order/review controls, validation errors,
  operation failures, dark-theme pressed controls, 320 CSS-pixel reflow,
  320×225 focus visibility, forced-colors emulation, development StrictMode
  remounts, initial summary failure recovery, and stopping-session polling.
- Material change: replacement of handwritten base controls and theme aliases
  with React and `@fluentui/react-components` v9 under `FluentProvider`.
- Exclusions and rationale: OBS Overlay remains the separate viewer-facing
  surface defined by ADR 0009.

## Optional manual environment

- Windows: Not recorded; optional manual review not run.
- Browser and version: Playwright Chromium for automated checks; manual browser
  version not recorded.
- Display scale and browser zoom: automated 320 CSS-pixel checks completed;
  optional manual 200% and 400% checks not run.
- Keyboard/input devices: automated keyboard checks completed; optional manual
  device details not recorded.
- Screen reader and version: Not run (advisory).
- Windows Contrast Themes: browser forced-colors emulation passed; named Windows
  Contrast Theme checks not run (advisory).

## Required automated gates

- `pnpm check:webui`: Pass.
- `pnpm build:webui`: Pass; 2,140 modules transformed into an offline local
  bundle.
- `pnpm test:webui-dev`: Pass, 1/1 test on 2026-07-18; the Vite development
  entry loads Home under React StrictMode's setup/cleanup/setup cycle.
- `pnpm test:a11y`: Pass, 36/36 tests on 2026-07-18. All seven Navigation
  Entries passed light/dark axe scans with zero detected WCAG 2.2 A/AA
  violations. Keyboard, focus, language/theme, validation, failure,
  forced-colors, pressed-state contrast, persistent live-region, summary retry,
  stopping-poll terminal state, and 320 CSS-pixel Timeline/Settings/Data
  Operations/short-viewport checks passed.
- Python regression suite: Pass, 266/266 tests on 2026-07-18.
- Report binding: Pass; `scripts/verify_accessibility_report.py` recomputed both
  asset hashes from the working tree and from committed revision
  `4085e23b10c0719de6ea8f0df4177ae1de9dbe6a`.
- CI run: Pending.

## Optional manual observations

### Keyboard and focus

- Result: Not run (advisory).
- Suggested follow-up: complete keyboard-only traversal when risk or available
  test time justifies it.

### Screen reader

- Result: Not run (advisory).
- Suggested follow-up: record browser and screen-reader versions plus landmark,
  control-name/state, table, live-region, validation, and language observations.

### Zoom, reflow, and text spacing

- Result: Not run (advisory).
- Automated evidence: Timeline, Settings, and Data Operations had no page-level
  horizontal overflow at the 320 CSS-pixel equivalent; the Timeline table kept
  its two-dimensional overflow in a labelled local region.
- Suggested follow-up: manually verify 200%/400% zoom and the checklist text
  spacing overrides when appropriate.

### Light, dark, system, and Windows high contrast

- Result: Not run (advisory).
- Automated evidence: official light/dark Fluent Web Themes and browser
  forced-colors checks passed.
- Suggested follow-up: verify system-theme changes and named light/dark Windows
  Contrast Themes when appropriate.

## Open issues

- No automated WCAG 2.2 A/AA violation or known release-blocking accessibility
  defect remains in the tested sample.
- Optional manual review was not performed. Under ADR 0012, its absence does not
  block this report, merge, or release.

## Conclusion

The required automated and asset-binding gates pass for the identified bundle,
so this report is `Result: Pass`. Optional manual observations were not run, and
this automated pass is not a claim of complete WCAG conformance.
