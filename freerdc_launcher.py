"""Entry point for packaging (PyInstaller). The package's own __main__.py uses relative
imports, which only work when run as `python -m freerdc`, not as a bundled script."""
from freerdc.__main__ import main

raise SystemExit(main())
