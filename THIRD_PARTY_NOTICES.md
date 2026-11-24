# Third-party software

FreeRDC's own code is released under the [MIT License](LICENSE). It uses the software below.
This file applies to the source repository and to the built bundles (folder or single file).

## FreeRDP (not included)

FreeRDC does not contain or link FreeRDP. It starts the FreeRDP client programs you have installed
(`xfreerdp`, `wlfreerdp`, `sdl-freerdp`, versions 2 and 3) as separate processes and passes them
command-line options. FreeRDP is licensed under the Apache License 2.0
(<https://github.com/FreeRDP/FreeRDP/blob/master/LICENSE>); its license applies to your copy of FreeRDP,
not to FreeRDC. FreeRDC is an independent project and is not affiliated with or endorsed by the FreeRDP project.

"Remote Desktop Connection" and "Windows" are trademarks of Microsoft Corporation. FreeRDC only imitates the
layout of the Windows dialog so that it is familiar; it is not affiliated with or endorsed by Microsoft.

## Qt and PySide6 (LGPL-3.0)

FreeRDC's user interface uses **Qt 6** through **PySide6** and **Shiboken6** (the Qt for Python project).
These are licensed under the GNU Lesser General Public License version 3 (also available under GPL-2.0/GPL-3.0).
Full texts: [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt) and [licenses/GPL-3.0.txt](licenses/GPL-3.0.txt),
which the LGPL incorporates.

- Qt and PySide6 are **not modified**. They are used as shared libraries and Python extension modules.
- In the folder build (`MODE=onedir`, the default) they are ordinary files in the `_internal` directory next to
  the program. You can replace them with your own compatible build of Qt or PySide6 (for example a version you
  compiled yourself) and the program will use it. In the single-file build the same files are packed inside the
  executable; use the folder build if you want to swap libraries.
- Source code: Qt <https://download.qt.io/official_releases/qt/> and <https://code.qt.io/cgit/>;
  PySide6 / Shiboken6 <https://code.qt.io/cgit/pyside/pyside-setup.git/> (the versions used are listed in
  `requirements.txt` and printed by `freerdc --self-test`).
- Nothing in FreeRDC's license restricts you from modifying the bundle for your own use or from reverse
  engineering it to debug such modifications.

## Other components in the bundle

| Component | License | Note |
|---|---|---|
| Python (interpreter and standard library) | PSF License 2.0 | <https://docs.python.org/3/license.html> |
| keyring, jaraco.classes, jaraco.context, jaraco.functools, more-itertools, jeepney | MIT | |
| SecretStorage, pycparser | BSD-3-Clause | |
| cryptography, cffi | Apache-2.0 or BSD-3-Clause; MIT-0 | cryptography includes OpenSSL (Apache-2.0) |
| importlib_metadata, zipp, packaging | Apache-2.0 | |
| Shared libraries the bundler copies from the build machine (GLib, D-Bus, ICU, FreeType, fontconfig, libgcrypt, libkrb5, ...) | mostly LGPL-2.1+, MIT/BSD-style, ICU and FreeType licenses | Each package's own license files are in the build machine's distribution |
| PyInstaller bootloader | GPL-2.0-or-later with the PyInstaller exception | The exception allows the bootloader to be included in programs under any license |

The license files that come with the Python packages are kept in the `*.dist-info` folders inside
the bundle's `_internal` directory.

## Build and development tools (not distributed)

PyInstaller and its hooks, pip and setuptools are used to build the bundle and are not part of the program.
