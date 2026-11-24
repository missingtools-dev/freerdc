#!/bin/bash
# Build the distributable bundle on this machine, with no Docker.
#   packaging/build-native.sh               -> dist-native/freerdc/  (onedir)
#   MODE=onefile packaging/build-native.sh
#
# The bundle contains copies of this machine's libraries, so it runs on this distro
# version and newer, but not on older ones. For a bundle that runs on Ubuntu 22.04 and
# everything newer, use packaging/build-in-docker.sh instead.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
if [ ! -x .venv-build/bin/python ]; then
	python3 -m venv .venv-build || {
		echo "Could not create a virtualenv. On Debian/Ubuntu install python3-venv." >&2
		exit 1
	}
fi
.venv-build/bin/pip install -q --upgrade pip
.venv-build/bin/pip install -q -r requirements.txt

PATH="$PWD/.venv-build/bin:$PATH" DIST_DIR="${DIST_DIR:-dist-native}" \
	WORK_DIR="${WORK_DIR:-build-native}" MODE="${MODE:-onedir}" ./build.sh

echo "built: ${DIST_DIR:-dist-native}/freerdc"
echo "glibc here: $(ldd --version | head -1 | awk '{print $NF}') (the bundle needs at least this on the machine that runs it)"
