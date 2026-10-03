# DanceTrail rename acceptance report

Evidence kind: `Product rename and clean configuration boundary`
Identifier: `2026-10-03-dancetrail-rename`
Evaluated revision: `1fcd5d0a9a193daae547d1eefb30663014e49a9b`
Asset SHA-256 (`dance_trail/webui_dist/app.js`): `0a5fe68179001db47f5ada6987dba8d525a67208831fa79fd5be3721a7b9ec04`
Asset SHA-256 (`dance_trail/webui_dist/index.html`): `653472120707a9466aae1cf89db5cdc545325370a0b9ad5a6710f4862304c958`
Evaluator: Automated project acceptance checks
Date: `2026-10-03`
Result: Pass

## Scope

The product title, desktop tray, Python package, configuration/database paths,
browser storage keys, bootstrap marker, CSRF header, and build artifacts use
DanceTrail naming. Legacy local configuration is no longer read or migrated.
The source version remains 0.8.0. Historical tags are preserved; previous
Release records and binary assets are not imported into this repository.

## Verification

- Python regression suite: 306/306 passed.
- Ruff and ty: passed.
- Frontend lint, type checks, and production build: passed.
- Playwright accessibility acceptance: 40/40 passed.
- Playwright development-mode acceptance: 1/1 passed.
- Portable CLI and desktop single-instance/startup-takeover smoke: passed.
- License collection: 99 dependency distributions plus native-library notices.

The generated HTML was normalized to LF for reproducible builds; this does
not change rendered markup. No new manual screen-reader or physical Windows
Contrast Theme evaluation was performed. Automated checks do not establish
complete manual WCAG conformance.
