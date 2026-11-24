#!/bin/bash
# Pack a built folder bundle into dist-docker/freerdc-<version>-linux-x86_64.tar.gz (+ .sha256).
#   packaging/make-release.sh [dist-dir]      (default dist-docker; build it first)
# Unpacking gives one folder, freerdc/, with the program and the licence files inside.
set -euo pipefail
cd "$(dirname "$0")/.."
DIST="${1:-dist-docker}"
[ -x "$DIST/freerdc/freerdc" ] || { echo "No folder build in $DIST/freerdc; run packaging/build-in-docker.sh first." >&2; exit 1; }
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' freerdc/__init__.py)"
ARCHIVE="freerdc-$VERSION-linux-x86_64.tar.gz"
tar -C "$DIST" --owner=0 --group=0 -czf "$DIST/$ARCHIVE" freerdc
(cd "$DIST" && sha256sum "$ARCHIVE" > "$ARCHIVE.sha256")
echo "$DIST/$ARCHIVE"; cat "$DIST/$ARCHIVE.sha256"
