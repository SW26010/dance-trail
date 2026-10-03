# Exit confirmation accessibility evaluation

Evidence kind: `Material base-component change`
Identifier: `2026-10-03-exit-dialog-focus`
Evaluated revision: `38ec86aaa6f060b4919681bcda59360d57efa9be`
Asset SHA-256 (`dance_trail/webui_dist/app.js`): `97f4d21c63424f8abbdc8fce6c403f36911d9f127e763595a12dd3520a94461a`
Asset SHA-256 (`dance_trail/webui_dist/index.html`): `653472120707a9466aae1cf89db5cdc545325370a0b9ad5a6710f4862304c958`
Evaluator: Local automated Playwright acceptance checks
Date: `2026-10-03`
Result: Pass

## Scope and change

The exit confirmation uses a native modal dialog with Fluent semantic styling
and buttons. This removes the hidden, focusable Tabster helper nodes that
triggered `aria-hidden-focus` violations on Home in light, dark, and forced-colors
modes. No axe rules or scan targets were excluded.

The dialog has an accessible name and description, starts focus on Cancel,
keeps background controls out of keyboard navigation, and restores focus to
the trigger after cancellation. Escape closes through React state to avoid a
delayed native close event interfering with immediate reopening. During an
exit request, Cancel and Escape cannot dismiss the confirmation; a failed
request restores cancellation and retry.

## Required automated gates

- `pnpm check:webui`: passed (lint and TypeScript).
- `pnpm build:webui`: passed; bundle size advisory remains.
- `pnpm test:a11y`: 43/43 passed, including all seven primary routes in light
  and dark themes, forced-colors Home, and three new open/close dialog tests.
- New dialog checks cover accessible name/description, initial focus, Tab and
  Shift+Tab, background focus exclusion, Escape, immediate reopening, Cancel,
  focus restoration, and axe scans with the dialog open and after closing.
- `pnpm test:webui-dev`: 3/3 passed, including StrictMode loading, pending exit
  Escape protection, cancellation, failure/retry, and accepted exit controls.
- CI run: not dispatched; these results are from local Windows Chromium runs.
- Asset binding: verified against the implementation commit above by
  `scripts/verify_accessibility_report.py`; the report follow-up is checked
  with `scripts/verify_accessibility_changes.py`.

## Optional manual observations

- Physical keyboard, screen reader, browser zoom, and Windows Contrast Theme
  review: Not run (advisory). Forced colors and keyboard behavior above were
  exercised through Playwright.

## Conclusion

All required automated checks passed for the recorded assets. No known blocking
accessibility defect remains in the evaluated scope. Automated results do not
establish complete WCAG conformance.
