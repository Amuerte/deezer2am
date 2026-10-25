"""Helpers shared by the tests (fixtures are in conftest.py)."""

import json
from pathlib import Path

from responses import matchers

from deezer_api import DeezerApi

FIXTURES = Path(__file__).parent / "fixtures"
API = DeezerApi.BASE_URL


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def mock_paginated_tracks(api):
    api.get(f"{API}/playlist/3333333333/tracks",
            json=fixture("playlist_tracks_page1"),
            match=[matchers.query_param_matcher({"limit": "100"})])
    api.get(f"{API}/playlist/3333333333/tracks",
            json=fixture("playlist_tracks_page2"),
            match=[matchers.query_param_matcher({"limit": "100", "index": "1"})])
