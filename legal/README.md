# Release license notices

The project is MIT licensed; see the root `LICENSE`. Dependencies retain their
own copyright and license terms. The same project license applies to the
project's earlier source revisions; it does not relicense third-party software.

`scripts/collect_licenses.py` runs during portable packaging. It copies the
project license, the installed CPython license, tzlocal/tzdata notices, and
PyInstaller's license with its bootloader exception. It also traverses the
installed frontend runtime dependencies and includes their complete notices.
The list conservatively includes runtime dependencies that tree shaking may
remove; development-only tools are not included.

Some npm packages omit their license file. `javascript/sources.json` binds the
reviewed upstream texts to exact package versions. A new unrecognized package
without a license file fails packaging, rather than substituting a generic MIT
license that might omit the correct copyright holder.

`runtime/` contains additional notices for native libraries in the Windows
Python distribution. Its `sources.json` records upstream sources and hashes.
These were reviewed with Python 3.14.6 from python-build-standalone 20260623.
Review the native notices when changing the Python/native-library toolchain;
the collector does not infer every DLL's legal terms. Microsoft runtime terms
apply only to Microsoft's code. The portable release targets Windows.

The portable distribution excludes imageio and imageio-ffmpeg. Optional research
dependencies installed by users retain their own terms. If FFmpeg is ever
bundled again, review the actual build configuration and corresponding source
requirements before distribution; adding a license file alone is insufficient.

For a release, install the locked Python release group and frozen pnpm
dependencies, then run the normal portable build. Missing or empty dependency
notices stop the build. `Legal/manifest.json` contains only package versions and
relative notice paths, never local machine paths.
