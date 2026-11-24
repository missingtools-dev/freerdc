# Building and running the packaged app

## Build

    packaging/build-in-docker.sh          # -> dist-docker/freerdc/   (folder; run dist-docker/freerdc/freerdc)
    packaging/build-native.sh             # -> dist-native/freerdc/     (no Docker; this machine's libraries)
    MODE=onefile packaging/build-in-docker.sh   # one executable file instead of a folder (slower to start)
    MODE=onefile packaging/build-native.sh      # the same, without Docker

To make a release archive from the folder build: `packaging/make-release.sh` writes
`dist-docker/freerdc-<version>-linux-x86_64.tar.gz` and its `.sha256`.

Use the Docker build for a bundle you want to share: it is built inside an **Ubuntu 22.04** container on purpose. A PyInstaller bundle
contains copies of the build machine's libraries, so it needs at least that machine's glibc.
Building on 22.04 (glibc 2.35) gives a bundle that runs on 22.04 and everything newer. The
same bundle built natively on Debian 13 needed glibc 2.39 and would not run on Debian 12 or Ubuntu 22.04.
The native build is fine for your own machine or for users who all run the same distro version or newer.
It needs `python3` with the `venv` module, creates `.venv-build/`, and prints the glibc it was built against.

Check it with `freerdc --self-test`: it starts the real window code and prints the Qt version,
whether the keyring is usable, and for each FreeRDP client it finds whether the client's
help lists every option FreeRDC uses.

## What the target machine needs

The bundle includes Python, Qt and the X11/xcb libraries. It does **not** include the
graphics-driver-related libraries or FreeRDP:

| | Debian / Ubuntu / Mint | Fedora |
|---|---|---|
| OpenGL/EGL (a normal desktop already has them) | `libegl1 libgl1` | `mesa-libEGL mesa-libGL` |
| FreeRDP (at least one) | `freerdp2-x11` or `freerdp3-x11` (+ `freerdp3-sdl`) | `freerdp` |
| Saved passwords | a running Secret Service (GNOME Keyring or KWallet) | same |

Without a keyring the app still works; "Allow me to save credentials" is then disabled.

## Verified (bundle built on Ubuntu 22.04, run inside containers under a virtual X server)

`freerdc --self-test` with `FREERDC_TEST_HOST`, `FREERDC_TEST_USER` and `FREERDC_TEST_PASSWORD` set also makes
real connections with every FreeRDP client it finds, once with default options and once with many
options (size, colour depth, smart sizing, sound, microphone, shared folders, NLA, H.264,
floatbar), then disconnects. All of these connected, both scenarios, to a Windows 10 test machine:

| Distro | glibc | FreeRDP clients tested |
|---|---|---|
| Ubuntu 22.04 | 2.35 | 2.6.1 |
| Debian 12 | 2.36 | 2.11.7 |
| Ubuntu 24.04 (= Linux Mint 22 base) | 2.39 | 2.11.5 |
| Debian 13 | 2.41 | 3.15.0 (x11, sdl) |
| Fedora 44 | 2.43 | 3.32.1 (x11, sdl) |

Not covered: a full desktop session on those distros (only a virtual X server), the Wayland
platform plugin inside containers, ARM (this is an x86-64 build), server-side failure cases
other than those exercised during development (wrong password, unknown host, closed port, ...).

## H.264

The Ubuntu builds of FreeRDP 2 (2.6.1 and 2.11.5) are built without H.264 and do not list
`/gfx-h264`; given that option they reject the whole command line (`Unexpected keyword`,
exit code 23). FreeRDC reads each client's help, greys out the H.264 setting for such a client and
leaves the option out of the command. Debian 12's 2.11.7 and all FreeRDP 3 clients support it.

## Icon and menu entry

The icon (a monitor with the FreeRDP-style hare in a badge) is drawn in `freerdc/assets/freerdc.svg`;
`packaging/make_icons.py` renders the PNG sizes next to it. The bundle ships the PNGs and uses
them for the window and the systray. Linux executables carry no embedded icon, so to get the
application into the start menu (with its icon) run the built executable once with:

    /path/to/freerdc --install-desktop      # undo with --uninstall-desktop

This works for the single-file build too (the menu entry points at that file, so install it where
it will stay), and from a repository checkout `packaging/install-desktop.sh /path/to/freerdc` does the same.
The entry and icons go to `~/.local/share/applications` and `~/.local/share/icons`.
