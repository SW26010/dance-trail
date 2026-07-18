# Make Manual Web UI Accessibility Review Advisory

Date: 2026-07-18

## Status

Accepted

## Context

ADR 0009 made a complete manual WCAG-EM review a merge and release gate for
every material base-component change and every release. That process requires a
specific Windows, browser, screen-reader, zoom, and Contrast Theme matrix. It is
valuable evidence, but requiring the full matrix for routine delivery is too
costly for this project.

The Web UI now has route-level light/dark axe scans plus explicit keyboard,
focus, pressed-state contrast, reflow, forced-colors, validation, live-region,
and accessible-tree tests. Python tests protect the server/bootstrap contract,
and release reports are cryptographically bound to the evaluated Web UI assets.

## Decision

Manual Web UI accessibility review is advisory. Not performing keyboard-only,
screen-reader, real browser zoom, text-spacing, or Windows Contrast Theme checks
does not by itself block a merge or release and does not force an accessibility
report to remain `Result: Pending`.

The required accessibility gate is:

- TypeScript checking and a reproducible production Web UI build;
- the Python unit-test suite;
- `pnpm test:a11y`, including all configured Playwright and axe checks with no
  accessibility-rule allowlist;
- a report whose evaluated revision and generated asset SHA-256 values can be
  recomputed by the report verifier; and
- no known unresolved accessibility defect classified as release-blocking.

For a required report, `Result: Pass` means those automated and asset-binding
requirements pass and no known release-blocking defect remains. `Result: Fail`
means a required check failed or a known blocking defect remains. `Result:
Pending` means required automated or asset evidence is incomplete. Optional
manual sections may say `Not run (advisory)` without changing a passing result.

Manual findings are still useful. If an optional review discovers a real defect,
the finding is recorded and triaged normally; making the review optional does
not make a known defect acceptable. An automated pass is not represented as a
claim of complete WCAG conformance.

This decision supersedes only the mandatory-manual-review portions of ADR 0009.
Its Fluent 2, WCAG 2.2 AA target, WAI-ARIA APG, automated testing, and evidence
scope decisions remain in force.

## Consequences

Routine changes and releases no longer wait for a full assistive-technology
matrix. The high-value automated checks and reproducible evidence remain hard
gates, while manual review can be scheduled when risk, available hardware, or a
reported defect justifies it.

Reports and documentation must distinguish an automated accessibility pass from
complete standards conformance. Known failures remain visible and cannot be
hidden by omitting optional manual testing.
