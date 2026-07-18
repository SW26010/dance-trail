# Local Web UI WCAG-EM Release Checklist

Use this procedure for every release and after a material change to a base Web
UI component. It evaluates the seven Local Web UI Navigation Entries. The OBS
Overlay is a separate viewer-facing output surface.

## 1. Establish the evaluation

1. Choose the evidence path and copy `release-report-template.md` there:
   - release: `release-reports/<exact-version-tag>.md`, for example
     `release-reports/v0.1.0.md`;
   - material base-component change:
     `change-reports/YYYY-MM-DD-<lowercase-kebab-slug>.md`, for example
     `change-reports/2026-07-18-fluent2-webui-baseline.md`.
2. Record the exact commit, Windows build, Edge/Chrome version, display scale,
   input devices, and assistive technologies.
3. Include Home, Timeline, Catalog, Lists, Insights, Data Operations, and
   Settings. Sample loading, empty, populated, disabled, validation error,
   operation failure/success, and saved/unsaved states where they exist.
4. Run the automated prerequisite:

   ```powershell
   uv sync --locked --cache-dir .uv-cache
   pnpm install --frozen-lockfile
   pnpm exec playwright install chromium
   pnpm test:a11y
   ```

   All tests and all WCAG 2.2 A/AA axe scans must pass with no allowlist.

## 2. Keyboard

- Use only the keyboard from a fresh page load. Verify the skip link, logical
  focus order, visible Fluent focus indicator, and no keyboard trap.
- Operate every navigation link, command button, toggle, search field, date
  control, native select, Settings editor, Timeline review action, and Data
  Operation parameter.
- Verify focus moves to a destination heading after in-app navigation, to the
  first invalid field after validation failure, and back to the initiating
  command after an asynchronous operation.
- Confirm focused controls are not obscured at normal size, 200% zoom, or 400%
  zoom/reflow.
- If a custom APG widget exists, execute its documented APG key table, including
  Escape, arrow, Home/End, Tab/Shift+Tab, activation, focus entry, and focus
  return as applicable.

## 3. Screen reader

- Test current NVDA with current Edge or Chrome. Use Windows Narrator as a
  secondary check when a Windows-specific behavior is involved.
- Navigate by landmarks and headings. Confirm one main landmark, the named
  application/primary navigation, one page heading, and a coherent heading
  hierarchy.
- Confirm every form control and icon-only button has a concise accessible name;
  descriptions, required/invalid state, pressed state, disabled state, and
  current-page state are announced.
- Confirm table captions and column headers are announced and static tables do
  not claim Grid interaction.
- Confirm validation, save, copy, live-state, and operation results are announced
  once at an appropriate urgency without unexpectedly moving the virtual cursor.
- Switch English/Chinese and verify the document language and translated names.

## 4. Zoom, reflow, and text spacing

- At 200% browser zoom, verify no content or function is lost.
- At 400% zoom (or a 320 CSS-pixel equivalent viewport), verify single-axis
  reflow except for genuinely two-dimensional tables. Any table scrolling must
  remain local and keyboard reachable.
- Apply the WCAG text-spacing overrides (1.5 line height, 2× paragraph spacing,
  0.12em letter spacing, 0.16em word spacing) and verify no clipping, overlap,
  or loss of controls.

## 5. Windows high contrast and themes

- Test light, dark, and system theme selection.
- Enable at least one dark and one light Windows Contrast Theme. Verify text,
  focus, selected navigation, borders, buttons, inputs, status meaning, and
  disabled controls remain perceivable.
- Confirm color is never the only carrier of status or action meaning.

## 6. Record the result

- Record each observation and link every defect to a reproducible issue.
- Set `Result: Pass` only when no WCAG 2.2 A/AA failure remains in the evaluated
  scope. Otherwise set `Result: Fail` and block the release.
- Commit the report before creating the version tag. The release workflow checks
  that `release-reports/<tag>.md` exists and says `Result: Pass`.
- Do not merge a material base-component change while its report is missing or
  says `Result: Pending` or `Result: Fail`.
- Do not use a Lighthouse score as a conformance claim. Record it only as an
  optional supporting signal.
