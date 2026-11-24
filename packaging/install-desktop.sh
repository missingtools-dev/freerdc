#!/bin/bash
# Add FreeRDC to the application menu of the current user (start menu entry + icons).
# Usage: packaging/install-desktop.sh /path/to/freerdc   (the built executable, either build mode)
# The executable can also do this itself:  freerdc --install-desktop   (undo: --uninstall-desktop)
set -e
exec "$(readlink -f "${1:?path to the freerdc executable}")" --install-desktop
