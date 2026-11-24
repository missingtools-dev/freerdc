#!/bin/bash
# Build with PyInstaller. MODE=onefile for a single executable (default: onedir).
# Output goes to ./dist/freerdc; override DIST_DIR / WORK_DIR to build elsewhere.
#
# Compatibility: the bundle contains copies of this machine's libraries, so it needs
# at least the glibc of the machine it was built on. Build on the OLDEST distro you
# want to support (see README) for a binary that runs on that one and everything newer.
set -e
cd "$(dirname "$0")"
MODE="${MODE:-onedir}"
DIST_DIR="${DIST_DIR:-dist}"
WORK_DIR="${WORK_DIR:-build}"
pyinstaller --noconfirm --clean --windowed --name freerdc --"$MODE" \
	--paths . \
	--add-data "$PWD/freerdc/assets:freerdc/assets" \
	--collect-submodules keyring.backends \
	--distpath "$DIST_DIR" --workpath "$WORK_DIR" --specpath "$WORK_DIR" \
	freerdc_launcher.py

# Licence texts travel with the program (the LGPL requires the licence to accompany Qt).
if [ "$MODE" = onedir ]; then
	notices="$DIST_DIR/freerdc"
else
	notices="$DIST_DIR/freerdc-licenses"
fi
mkdir -p "$notices"
cp LICENSE THIRD_PARTY_NOTICES.md "$notices/"
cp -r licenses "$notices/"
