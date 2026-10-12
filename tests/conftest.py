"""Shared pytest configuration.

Windows fix: pytest-homeassistant-custom-component calls
``pytest_socket.disable_socket(allow_unix_socket=True)`` in its
``pytest_runtest_setup`` hook (Linux assumption). Windows' Proactor event loop
builds its self-pipe pair with AF_INET sockets, so every test would die in
fixture setup with ``SocketBlockedError``. A separate hook can't intercept
this (same hook phase), so ``disable_socket`` is replaced with a no-op on
import under Windows. The socket block stays active on Linux/CI.
"""

import sys

import pytest
import pytest_socket

if sys.platform == "win32":

    def _disable_socket_windows_noop(allow_unix_socket: bool = False) -> None:
        pass

    pytest_socket.disable_socket = _disable_socket_windows_noop


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
