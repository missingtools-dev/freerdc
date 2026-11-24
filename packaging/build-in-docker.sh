#!/bin/bash
# Build the distributable bundle inside an Ubuntu 22.04 container.
#   packaging/build-in-docker.sh            -> dist-docker/freerdc/  (onedir)
#   MODE=onefile packaging/build-in-docker.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${OUT:-dist-docker}"
IMAGE=freerdc-build:ubuntu22
docker build -q -t "$IMAGE" -f packaging/Dockerfile.build packaging >/dev/null
mkdir -p "$OUT"
# Run as the calling user so the files in $OUT are not root-owned; HOME and the virtualenv
# live in the container's /tmp.
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e MODE="${MODE:-onedir}" \
    -v "$PWD":/src:ro -v "$PWD/$OUT":/out "$IMAGE" bash -c '
  set -e
  python3 -m venv /tmp/venv
  /tmp/venv/bin/pip install -q --upgrade pip
  /tmp/venv/bin/pip install -q -r requirements.txt
  cp -r /src /tmp/work && cd /tmp/work
  PATH=/tmp/venv/bin:$PATH DIST_DIR=/out WORK_DIR=/tmp/pybuild ./build.sh
'
echo "built: $OUT/freerdc"
