# Use Fluent UI React v9 for the Local Web UI

Date: 2026-07-18

## Status

Accepted

## Context

ADR 0009 made Fluent 2 the Local Web UI design authority, but the first
implementation copied semantic colors and rebuilt buttons, cards, inputs,
messages, badges, and other controls in one Python-embedded HTML/CSS/JavaScript
asset. That made visual alignment dependent on local replicas of Fluent rules
and concentrated unrelated application, interaction, and rendering code in one
file.

The Local Web UI still has to run offline, share the existing localhost HTTP
and CSRF contract, and remain available in the PyInstaller portable build.

## Decision

The Local Web UI uses React with `@fluentui/react-components` v9 as its frontend
implementation. The application root is a `FluentProvider`; light and dark
rendering use the official `webLightTheme` and `webDarkTheme`, while the system
choice tracks `prefers-color-scheme`. Custom layout styles use Fluent design
tokens through `makeStyles`. Official Fluent controls are used directly rather
than hidden behind pass-through project wrappers.
The suite's Nav package is explicitly documented as not production-ready, so
primary navigation uses official Fluent Link controls inside a semantic `nav`.

The maintainable source of truth lives under `webui/`. Vite produces a locked,
self-contained bundle under `dancing_log/webui_dist/`; no CDN or runtime package
download is permitted. Python owns the narrow static-asset delivery and
request-local bootstrap interface, including CSRF and canonical Navigation Entry
routes. The portable build rebuilds the frontend and includes the generated
assets explicitly.

Static data remains a semantic HTML table through Fluent Table. Custom composite
widgets remain subject to the WAI-ARIA APG and dedicated interaction tests from
ADR 0009.

## Consequences

Frontend changes require the locked pnpm graph, TypeScript checking, a production
Web UI build, and the Playwright accessibility suite. Generated files in
`dancing_log/webui_dist/` are build output and are not edited by hand.

The initial bundle is larger than the handwritten asset, but it replaces local
control implementations with maintained Fluent behavior and keeps theme,
accessibility, and interaction knowledge at the official component seams.
