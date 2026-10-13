"""pytest plugin: run Home Assistant tests on native Windows.

`homeassistant.runner` imports `fcntl` and `homeassistant.util.resource` imports
`resource` (both Unix-only). pytest-homeassistant-custom-component imports them while
loading its plugin, BEFORE any conftest.py runs, so pytest cannot start on Windows.
This plugin installs harmless stubs first. It is loaded via `addopts = "-p win_compat"`
in pyproject.toml; run `python -m pytest` so the repo root is on sys.path.
No effect on Linux/CI.
"""

import sys
import types

if sys.platform == "win32":
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX, fcntl.LOCK_NB, fcntl.LOCK_UN = 2, 4, 8
    fcntl.flock = lambda fd, operation: None

    resource = types.ModuleType("resource")
    resource.RLIMIT_NOFILE = 7
    resource.getrlimit = lambda which: (1 << 20, 1 << 20)
    resource.setrlimit = lambda which, limits: None

    sys.modules.setdefault("fcntl", fcntl)
    sys.modules.setdefault("resource", resource)
