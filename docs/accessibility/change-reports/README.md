# Accessibility material-change reports

Use this directory for accessibility evidence created after a material change
to a base Local Web UI component when that change is not itself a release.

Copy `../release-report-template.md` to
`YYYY-MM-DD-<lowercase-kebab-slug>.md`. The slug must identify the change, not a
branch or contributor. Identify the evaluated revision and reproducible asset
hashes. A `Result: Pending` report documents incomplete required automation or
asset evidence; optional manual observations may be `Not run (advisory)`. The
change must not merge until the report says exactly `Result: Pass`.

A passing report must name the full 40-character SHA of a committed revision
that contains the recorded Web UI asset bytes. Commit the implementation first,
then add or finalize its report in a report-only follow-up commit. The Web UI CI
checks this binding across the complete pull-request or push change set.

Release evidence belongs in `../release-reports/<exact-version-tag>.md`.
