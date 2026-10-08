# Third-party notices

Fuma's original code and documentation are licensed under MIT; see LICENSE.
Third-party dependencies retain their own copyrights and licenses.

## Character artwork

The name Fuma references Ultraman Fuma from Ultraman Taiga.
The character artwork used by the project avatar, favicon and application icons
belongs to Tsuburaya Productions (円谷プロダクション). © 円谷プロダクション.
These assets are excluded from Fuma's MIT license. Attribution does not grant
permission to use or redistribute them. Fuma is an unofficial project and is not
affiliated with, sponsored by, or endorsed by Tsuburaya Productions.

## Generated dependency notices

The frontend build includes dependency-licenses.json and THIRD_PARTY_LICENSES.txt,
generated from the dependencies actually bundled by Vite. The backend image
includes THIRD_PARTY_LICENSES.json under /usr/share/licenses/fuma, generated from
its installed Python runtime dependencies. These files contain dependency
versions, license metadata, and license texts. Python wheels and source packages
include Fuma's LICENSE and this notice; dependencies are distributed separately.

The generation checks detect missing license texts and unreviewed license labels.
They do not replace compliance review of a release, bundled native libraries,
operating-system packages, or artwork rights.

## Dependencies requiring additional attention

- Psycopg and psycopg-binary use LGPL-3.0-only. Preserve their license files and
  copyright notices, permit replacement of the library, and satisfy applicable
  corresponding-source obligations when redistributing binaries. The binary
  package also bundles native libraries with their own licenses.
  Source and license: https://github.com/psycopg/psycopg
- Redis 8 is a separate service, available under a choice of RSALv2, SSPLv1 or
  AGPLv3. Fuma's MIT license does not relicense Redis. A distributor or operator
  must choose and comply with the applicable Redis terms.
  https://redis.io/legal/licenses/
- The parser image contains Android tools, a Java runtime, Python and Debian
  packages; the frontend image also includes Caddy and Alpine packages. Preserve
  the upstream notices and applicable source provisions when distributing images.
  The generated Python and JavaScript inventories do not cover these OS packages.
