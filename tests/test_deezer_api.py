import pytest
import requests
from loguru import logger
from responses import matchers

from deezer_api import DeezerApi, DeezerError
from helpers import API, fixture, mock_paginated_tracks


def test_user_id_is_read_from_environment():
    assert DeezerApi().user_id == "1000001"


def test_explicit_user_id_overrides_environment():
    assert DeezerApi(user_id="42").user_id == "42"


def test_get_user_playlists_uses_environment_user_id(api):
    api.get(f"{API}/user/1000001/playlists",
            json=fixture("user_playlists"),
            match=[matchers.query_param_matcher({"limit": "100"})])

    playlists = DeezerApi().get_user_playlists()

    assert [p["id"] for p in playlists] == [1111111111, 2222222222]
    assert playlists[0]["title"] == "Test playlist 1"
    assert playlists[0]["nb_tracks"] == 13


def test_get_user_playlists_with_explicit_user_id(api):
    api.get(f"{API}/user/42/playlists", json=fixture("user_playlists"))

    assert len(DeezerApi().get_user_playlists(user_id=42)) == 2


def test_get_user_playlists_without_user_id_raises(monkeypatch):
    monkeypatch.delenv("DEEZER_USER_ID")

    with pytest.raises(ValueError, match="DEEZER_USER_ID"):
        DeezerApi().get_user_playlists()


def test_get_playlist_tracks_follows_pagination(api):
    api.get(f"{API}/playlist/3333333333/tracks",
            json=fixture("playlist_tracks_page1"),
            match=[matchers.query_param_matcher({"limit": "100"})])
    api.get(f"{API}/playlist/3333333333/tracks",
            json=fixture("playlist_tracks_page2"),
            match=[matchers.query_param_matcher({"limit": "100", "index": "1"})])

    tracks = DeezerApi().get_playlist_tracks(3333333333)

    assert [t["id"] for t in tracks] == [900000001, 900000002]
    assert [t["isrc"] for t in tracks] == ["XXA011500001", "XXB016900001"]
    assert tracks[0]["artist"]["name"] == "The Lanterns"


def test_get_playlist_tracks_raw_merges_pages_into_one_response(api):
    mock_paginated_tracks(api)

    response = DeezerApi().get_playlist_tracks(3333333333, raw=True)

    page1, page2 = fixture("playlist_tracks_page1"), fixture("playlist_tracks_page2")
    assert response["data"] == page1["data"] + page2["data"]
    assert response["total"] == 2
    assert response["checksum"] == page1["checksum"]
    assert "next" not in response


def test_get_user_playlists_raw_returns_api_response(api):
    api.get(f"{API}/user/1000001/playlists", json=fixture("user_playlists"))

    assert DeezerApi().get_user_playlists(raw=True) == fixture("user_playlists")


def test_get_playlist_tracks_of_empty_playlist(api):
    api.get(f"{API}/playlist/1/tracks", json={"data": [], "total": 0})

    assert DeezerApi().get_playlist_tracks(1) == []


def test_get_track_returns_details_with_isrc(api):
    api.get(f"{API}/track/900000001", json=fixture("track"))

    track = DeezerApi().get_track(900000001)

    assert track["isrc"] == "XXA011500001"
    assert track["title"] == "Morning Light (Remastered 2015)"
    assert track["release_date"] == "2015-12-24"


def test_api_error_raises_deezer_error(api):
    # Deezer reports errors with an HTTP 200 and an "error" object
    api.get(f"{API}/playlist/1/tracks", json=fixture("error_no_data"))

    with pytest.raises(DeezerError) as excinfo:
        DeezerApi().get_playlist_tracks(1)

    assert excinfo.value.type == "DataException"
    assert excinfo.value.code == 800
    assert "no data" in str(excinfo.value)


def test_quota_error_is_retried(api, sleeps):
    api.get(f"{API}/track/900000001", json=fixture("error_quota"))
    api.get(f"{API}/track/900000001", json=fixture("track"))

    track = DeezerApi().get_track(900000001)

    assert track["id"] == 900000001
    assert sleeps == [5]


def test_quota_error_retry_is_logged(api, sleeps):
    api.get(f"{API}/track/900000001", json=fixture("error_quota"))
    api.get(f"{API}/track/900000001", json=fixture("track"))
    messages = []
    sink_id = logger.add(messages.append, level="WARNING", format="{level} {message}")

    try:
        DeezerApi().get_track(900000001)
    finally:
        logger.remove(sink_id)

    assert messages == ["WARNING Deezer quota exceeded, retrying in 5s (1/3)\n"]


def test_quota_error_raises_after_max_retries(api, sleeps):
    for _ in range(3):
        api.get(f"{API}/track/900000001", json=fixture("error_quota"))

    with pytest.raises(DeezerError) as excinfo:
        DeezerApi(max_retries=2).get_track(900000001)

    assert excinfo.value.code == DeezerApi.QUOTA_ERROR_CODE
    assert len(api.calls) == 3
    assert len(sleeps) == 2


def test_http_error_is_raised(api):
    api.get(f"{API}/track/1", status=500)

    with pytest.raises(requests.HTTPError):
        DeezerApi().get_track(1)
