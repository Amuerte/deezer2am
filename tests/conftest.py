import pytest
import responses

import deezer_api


@pytest.fixture
def api():
    """Mock the Deezer API; fails the test if a registered response isn't used."""
    with responses.RequestsMock() as mock:
        yield mock


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEZER_USER_ID", "1000001")
    # Missing data reports are written to the current directory by default
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def sleeps(monkeypatch):
    """Record the quota back-off sleeps instead of waiting."""
    calls = []
    monkeypatch.setattr(deezer_api, "sleep", calls.append)
    return calls
