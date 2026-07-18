# Accessibility release reports

Copy `../release-report-template.md` to `<exact-version-tag>.md` and complete the
required automated accessibility evidence for the identified revision before
creating that tag. The release workflow requires the matching file, an exact
`Result: Pass` line, a full evaluated commit SHA, and SHA-256 entries for both
committed Web UI assets. The
evaluated commit may precede the report-only commit, but it must be an ancestor of
the tag and contain the same asset bytes as the release build.

Do not place a blank template here: files in this directory are release evidence.
Material non-release changes belong in `../change-reports/` instead.
Manual observations are advisory and may be recorded as `Not run (advisory)`.
