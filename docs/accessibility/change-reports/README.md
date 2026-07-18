# Accessibility material-change reports

Use this directory for WCAG-EM evidence created after a material change to a
base Local Web UI component when that change is not itself a release.

Copy `../release-report-template.md` to
`YYYY-MM-DD-<lowercase-kebab-slug>.md`. The slug must identify the change, not a
branch or contributor. Identify the immutable revision that was manually
evaluated. A `Result: Pending` report can document unfinished evaluation work,
but the change must not merge until the report says exactly `Result: Pass`.

Release evidence belongs in `../release-reports/<exact-version-tag>.md`.
