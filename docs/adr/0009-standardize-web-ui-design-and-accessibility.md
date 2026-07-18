# Standardize the Web UI on Fluent 2 and WCAG 2.2 AA

Date: 2026-07-18

## Status

Accepted; mandatory manual-review gate superseded by
[ADR 0012](0012-make-manual-webui-accessibility-review-advisory.md)

## Context

The Local Web UI is the primary interaction surface of a Windows desktop
productivity tool. Its previous styling used one-off colors and component rules,
and its Python tests could not detect browser-level accessibility regressions.
The project needs one design authority and an acceptance process that covers
semantics and interaction as well as appearance.

Automated tools cannot establish complete WCAG conformance. Complex custom
widgets also need behavior-specific tests because static ARIA and axe scans do
not prove their keyboard or focus-management contracts.

## Decision

[Microsoft Fluent 2](https://fluent2.microsoft.design/) is the sole primary
design system for the Local Web UI. Treat it as a Windows desktop productivity
surface, not a SaaS marketing site or mobile application. Components consume
Fluent-style semantic aliases for color, type, spacing, radius, depth, and
interaction states. The interface uses Segoe UI Variable/Segoe UI, supports
system, light, and dark themes, and includes Windows forced-colors behavior.
Native HTML controls remain preferred where they satisfy the interaction.

[WCAG 2.2 Level AA](https://www.w3.org/TR/WCAG22/) is the accessibility target.
[WAI-ARIA APG](https://www.w3.org/WAI/ARIA/apg/) is authoritative for any custom
Dialog, Tabs, Menu, Combobox, Grid, or other composite widget. Static data stays
a native table; it must not be promoted to an ARIA Grid unless it actually owns
the Grid keyboard model.

Playwright and `@axe-core/playwright` scan every primary route in light and dark
themes with the WCAG 2.2 A/AA rule tags. Important data, validation, failure,
language, theme, focus, forced-colors, and toggle states have explicit tests.
ARIA snapshots or targeted accessible-role/name/state assertions protect the
accessibility tree. Introducing an explicit custom APG widget role fails the
inventory test until dedicated keyboard, focus, state, and ARIA tests are added.

Each release and each material base-component change also requires a recorded
[WCAG-EM](https://www.w3.org/WAI/test-evaluate/conformance/wcag-em/) manual check
covering keyboard use, screen readers, 200%/400% zoom and reflow, and Windows
high contrast. Release evidence is named
`docs/accessibility/release-reports/<exact-version-tag>.md`; non-release material
change evidence is named
`docs/accessibility/change-reports/YYYY-MM-DD-<lowercase-kebab-slug>.md`. Both
use the shared report template and identify the exact evaluated revision. A
release tag requires its matching passing report, and a material base-component
change must have a passing report before merge. `Result: Pending` records work
still to do and does not satisfy either requirement. Lighthouse Accessibility is
diagnostic only and is never evidence of WCAG 2.2 AA conformance.

The OBS Overlay remains a separate viewer-facing output surface rather than a
Local Web UI Navigation Entry. Its visual contract is not silently converted
into a desktop application shell by this decision.

## Consequences

The Web UI stays self-contained and offline: adopting Fluent 2 does not add a
CDN or require a framework rewrite. Semantic tokens make future visual changes
auditable, while native controls reduce custom interaction code.

Node development dependencies and a locked pnpm graph are now part of Web UI
testing. Pull requests and releases install Chromium and run the accessibility
suite. A zero-violation automated run is necessary but insufficient; release
owners must retain the manual evaluation report and unresolved findings block a
passing result.
