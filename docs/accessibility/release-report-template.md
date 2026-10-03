# Local Web UI Accessibility Evaluation Report

Evidence kind: `Release` or `Material base-component change`
Identifier: `<version tag or YYYY-MM-DD-lowercase-kebab-slug>`
Evaluated revision: `<full 40-character commit SHA for Result: Pass>`
Asset SHA-256 (`dance_trail/webui_dist/app.js`): `<64 lowercase hexadecimal characters>`
Asset SHA-256 (`dance_trail/webui_dist/index.html`): `<64 lowercase hexadecimal characters>`
Evaluator: `<automation run, name, or initials>`
Date: `YYYY-MM-DD`
Result: Pending

## Scope and sample

- Navigation Entries:
- Important states:
- Exclusions and rationale:

## Optional manual environment

- Windows: Not run (advisory).
- Browser and version: Not run (advisory).
- Display scale and browser zoom: Not run (advisory).
- Keyboard/input devices: Not run (advisory).
- Screen reader and version: Not run (advisory).
- Windows Contrast Themes: Not run (advisory).

## Required automated gates

- `pnpm test:a11y` result:
- CI run:

## Optional manual observations

### Keyboard and focus

- Result: Not run (advisory), or Pass/Fail when performed.
- Evidence/findings:

### Screen reader

- Result: Not run (advisory), or Pass/Fail when performed.
- Evidence/findings:

### Zoom, reflow, and text spacing

- Result: Not run (advisory), or Pass/Fail when performed.
- Evidence/findings:

### Light, dark, system, and Windows high contrast

- Result: Not run (advisory), or Pass/Fail when performed.
- Evidence/findings:

## Open issues

- None, or issue links with WCAG success criteria and release disposition.

## Conclusion

Replace `Result: Pending` above with exactly `Result: Pass` when all required
automated and asset-binding gates pass and no known release-blocking
accessibility defect remains. Use `Result: Fail` for a failed required gate or a
known blocking defect. Optional manual observations may remain `Not run
(advisory)` and do not block a passing result. Do not describe an automated pass
as complete WCAG conformance.
