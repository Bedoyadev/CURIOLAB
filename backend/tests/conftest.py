import pytest


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    """No test reaches a paid service: the keys are hidden from the code under test (the tests
    that exercise Claude or the voice replace those calls with fakes)."""
    from animation.shared import settings

    real = settings.secret
    monkeypatch.setattr(settings, "secret", lambda name, env_file=None: real(name, env_file) if name == "GODOT_BIN" or env_file else "")
