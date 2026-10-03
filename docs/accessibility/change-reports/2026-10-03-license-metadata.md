# Local Web UI Accessibility Evaluation Report

Evidence kind: `License metadata change with unchanged Web UI assets`
Identifier: `2026-10-03-license-metadata`
Evaluated revision: `dd21d7c438bdef8eeb589d505acb296bc356a480`
Asset SHA-256 (`dancing_log/webui_dist/app.js`): `d338f01a5564a619b779940b65bc07fca4673e848f78a2601ad87b179095f1fc`
Asset SHA-256 (`dancing_log/webui_dist/index.html`): `88c368311d9d2d509aa3cc272ead59006d9cddc1687f3a81114adb4c63957d11`
Evaluator: Automated project acceptance checks
Date: `2026-10-03`
Result: Pass

## Scope

`package.json` adds the project MIT license identifier. Runtime dependencies,
Web UI source, and generated asset bytes are unchanged from the evaluated
revision. The CI change checker now verifies a complete snapshot when the base
commit is unavailable, requiring valid evidence for the current asset hashes.
Historical reports for different asset versions cannot satisfy that requirement.

## Verification

- `pnpm check:webui`: Pass.
- `pnpm build:webui`: Pass; generated assets match the evaluated revision.
- `pnpm test:a11y`: Pass, 40/40 tests using Playwright Chromium.
- `pnpm test:webui-dev`: Pass, 1/1 test.
- Python regression suite: Pass, 306/306 tests, including missing-base evidence
  validation and runtime license-collection regressions.
- Ruff and ty: Pass.

No new manual screen-reader or physical Windows Contrast Theme evaluation was
performed. These automated results do not constitute a complete manual WCAG
conformance assessment.
