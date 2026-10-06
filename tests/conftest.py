import sys

import pytest

from tare import agents

# the platform the tests run on, before any test pins it
HOST = sys.platform


@pytest.fixture(autouse=True)
def linux_and_no_keychain(monkeypatch):
    """Tests describe Linux unless they say otherwise, and never touch the user's Keychain: on a
    Mac, Claude's adapter would otherwise read the real login."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(agents, "_security", lambda account, service: None)
