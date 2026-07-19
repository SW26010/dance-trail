# Local Web UI Accessibility Evaluation Report

Evidence kind: `Material base-component change`
Identifier: `2026-07-19-data-operation-safety-and-feedback`
Evaluated revision: `98c9e368acebac1b8969c7d9d9067074cba1dd5a`
Asset SHA-256 (`dancing_log/webui_dist/app.js`): `d338f01a5564a619b779940b65bc07fca4673e848f78a2601ad87b179095f1fc`
Asset SHA-256 (`dancing_log/webui_dist/index.html`): `88c368311d9d2d509aa3cc272ead59006d9cddc1687f3a81114adb4c63957d11`
Evaluator: Automated checks run through the Codex task
Date: `2026-07-19`
Result: Pass

## Scope and sample

- Navigation Entries: Home, Timeline, Catalog, Lists, Insights, Data Operations,
  and Settings.
- Important states: light/dark rendering, loading, Timeline request
  cancellation, validation errors, operation failures, optional and explicit
  zero row limits, invalid API success and error responses, keyboard focus return, 320
  CSS-pixel reflow, and forced-colors emulation.
- Material changes: asynchronous feedback now uses only Fluent MessageBar's
  announcement mechanism; the redundant outer live regions and Home card
  `aria-live` were removed. Data Operation integer drafts now preserve the
  distinction between unset and explicit zero. Success and error payloads are
  validated against centralized Zod schemas before they reach page state.
- Exclusions and rationale: OBS Overlay remains the separate viewer-facing
  surface defined by ADR 0009. No manual screen-reader run was performed.

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
- `pnpm build:webui`: Pass; 2,220 modules transformed into the offline local
  bundle with the hashes recorded above.
- `pnpm test:webui-dev`: Pass, 1/1 test on 2026-07-19.
- `pnpm test:a11y`: Pass, 40/40 tests on 2026-07-19. All seven Navigation
  Entries passed light/dark axe scans with zero detected WCAG 2.2 A/AA
  violations; the focused Timeline, feedback, row-limit, and malformed success
  and error response regressions passed.
- Python quality gates: Pass; Ruff checked `dancing_log`, `tests`, and `scripts`,
  and ty statically checked the complete `dancing_log` package.
- Python regression suite: Pass, 274/274 tests on 2026-07-19.
- Frozen portable build and smoke: Pass; both `/home` and `/assets/app.js`
  returned the required status, content type, and non-empty payload.
- Report binding: Pass. The evaluated implementation revision and both committed
  Web UI asset hashes are recorded above.
- CI run: Pending.

## Optional manual observations

### Keyboard and focus

- Result: Not run (advisory).
- Automated evidence: navigation, skip-link, Timeline scrolling, validation
  focus, and operation-trigger focus-return checks passed.

### Screen reader

- Result: Not run (advisory).
- Automated evidence: the redundant explicit live-region path was removed;
  Fluent MessageBar remains the single announcement owner.

### Zoom, reflow, and text spacing

- Result: Not run (advisory).
- Automated evidence: Timeline, Settings, and Data Operations retained local
  overflow and no page-level horizontal scrolling at 320 CSS pixels.

### Light, dark, system, and Windows high contrast

- Result: Not run (advisory).
- Automated evidence: official light/dark Fluent Web Themes and browser
  forced-colors checks passed.

## Open issues

- No automated WCAG 2.2 A/AA violation or known release-blocking accessibility
  defect remains in the tested sample.

## Conclusion

The implementation's required automated and immutable asset-binding gates pass.
Optional manual observations were not run, and the automated pass is not a
claim of complete WCAG conformance.
