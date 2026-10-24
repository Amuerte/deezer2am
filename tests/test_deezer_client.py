import csv
import io
import json
from pathlib import Path

import pytest
import requests
import responses
from loguru import logger
from responses import matchers

import deezer_api
import deezer_client
from deezer_api import DeezerApi, DeezerError

FIXTURES = Path(__file__).parent / "fixtures"
API = DeezerApi.BASE_URL


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def api():
    """Mock the Deezer API; fails the test if a registered response isn't used."""
    with responses.RequestsMock() as mock:
        yield mock


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("DEEZER_USER_ID", "1000001")


@pytest.fixture
def sleeps(monkeypatch):
    """Record the quota back-off sleeps instead of waiting."""
    calls = []
    monkeypatch.setattr(deezer_api, "sleep", calls.append)
    return calls


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


def mock_paginated_tracks(api):
    api.get(f"{API}/playlist/3333333333/tracks",
            json=fixture("playlist_tracks_page1"),
            match=[matchers.query_param_matcher({"limit": "100"})])
    api.get(f"{API}/playlist/3333333333/tracks",
            json=fixture("playlist_tracks_page2"),
            match=[matchers.query_param_matcher({"limit": "100", "index": "1"})])


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


def test_cli_json_prints_playlists_response(api, capsys):
    api.get(f"{API}/user/1000001/playlists", json=fixture("user_playlists"))

    deezer_client.main(["--json"])

    assert json.loads(capsys.readouterr().out) == fixture("user_playlists")


def test_cli_json_prints_merged_tracks_response(api, capsys):
    mock_paginated_tracks(api)

    deezer_client.main(["3333333333", "--json"])

    output = json.loads(capsys.readouterr().out)
    assert [t["isrc"] for t in output["data"]] == ["XXA011500001", "XXB016900001"]
    assert "next" not in output


def test_cli_without_json_prints_nothing_on_stdout(api, capsys):
    api.get(f"{API}/user/1000001/playlists", json=fixture("user_playlists"))

    deezer_client.main([])

    assert capsys.readouterr().out == ""


def test_cli_error_exits_with_status_1(api, capsys):
    api.get(f"{API}/playlist/1/tracks", json=fixture("error_no_data"))

    with pytest.raises(SystemExit) as excinfo:
        deezer_client.main(["1", "--json"])

    assert excinfo.value.code == 1
    assert capsys.readouterr().out == ""


def test_cli_csv_prints_tracks_in_convertsongs_format(api, capsys):
    mock_paginated_tracks(api)

    deezer_client.main(["3333333333", "--csv"])

    header, *rows = csv.reader(io.StringIO(capsys.readouterr().out))
    assert header == deezer_client.CSV_HEADER
    assert [row[16] for row in rows] == ["XXA011500001", "XXB016900001"]
    assert rows[0][1] == "Morning Light (Remastered 2015)"
    assert rows[0][3] == rows[0][7] == "The Lanterns"
    assert rows[0][5] == "Lantern Songs (Remastered 2015)"
    assert rows[0][12] == "429000"


def test_csv_header_passes_convertsongs_check():
    from csv_column_names import (valid_album_names_columns, valid_artist_names_columns,
                                  valid_track_names_columns)
    header = deezer_client.CSV_HEADER

    assert header[1] in valid_track_names_columns
    assert header[3] in valid_artist_names_columns
    assert header[5] in valid_album_names_columns
    assert header[16] == "ISRC"


def test_csv_row_escapes_commas_in_artist_name():
    track = fixture("track")
    track["artist"]["name"] = "Crosby, Stills & Nash"

    row = deezer_client.track_to_csv_row(track)

    assert row[3] == "Crosby\\, Stills & Nash"


def test_cli_csv_requires_playlist_id():
    with pytest.raises(SystemExit) as excinfo:
        deezer_client.main(["--csv"])

    assert excinfo.value.code == 2


def test_cli_csv_and_json_are_exclusive():
    with pytest.raises(SystemExit) as excinfo:
        deezer_client.main(["1", "--csv", "--json"])

    assert excinfo.value.code == 2
