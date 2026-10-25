import csv
import io
import json

import pytest
from loguru import logger

import deezer2am
from deezer_api import DeezerError
from helpers import API, fixture, mock_paginated_tracks


def test_cli_json_prints_playlists_response(api, capsys):
    api.get(f"{API}/user/1000001/playlists", json=fixture("user_playlists"))

    deezer2am.main(["--json"])

    assert json.loads(capsys.readouterr().out) == fixture("user_playlists")


def test_cli_json_prints_merged_tracks_response(api, capsys):
    mock_paginated_tracks(api)

    deezer2am.main(["3333333333", "--json"])

    output = json.loads(capsys.readouterr().out)
    assert [t["isrc"] for t in output["data"]] == ["XXA011500001", "XXB016900001"]
    assert "next" not in output


def test_cli_without_json_prints_nothing_on_stdout(api, capsys):
    api.get(f"{API}/user/1000001/playlists", json=fixture("user_playlists"))

    deezer2am.main([])

    assert capsys.readouterr().out == ""


def test_cli_error_exits_with_status_1(api, capsys):
    api.get(f"{API}/playlist/1/tracks", json=fixture("error_no_data"))

    with pytest.raises(SystemExit) as excinfo:
        deezer2am.main(["1", "--json"])

    assert excinfo.value.code == 1
    assert capsys.readouterr().out == ""


def test_cli_csv_prints_tracks_in_convertsongs_format(api, capsys):
    mock_paginated_tracks(api)

    deezer2am.main(["3333333333", "--csv"])

    header, *rows = csv.reader(io.StringIO(capsys.readouterr().out))
    assert header == deezer2am.CSV_HEADER
    assert [row[16] for row in rows] == ["XXA011500001", "XXB016900001"]
    assert rows[0][1] == "Morning Light (Remastered 2015)"
    assert rows[0][3] == rows[0][7] == "The Lanterns"
    assert rows[0][5] == "Lantern Songs (Remastered 2015)"
    assert rows[0][12] == "429000"


def test_csv_header_passes_convertsongs_check():
    from csv_column_names import (valid_album_names_columns, valid_artist_names_columns,
                                  valid_track_names_columns)
    header = deezer2am.CSV_HEADER

    assert header[1] in valid_track_names_columns
    assert header[3] in valid_artist_names_columns
    assert header[5] in valid_album_names_columns
    assert header[16] == "ISRC"


def test_csv_row_escapes_commas_in_artist_name():
    track = fixture("track")
    track["artist"]["name"] = "Crosby, Stills & Nash"

    row = deezer2am.track_to_csv_row(track)

    assert row[3] == "Crosby\\, Stills & Nash"


def test_cli_csv_requires_playlist_id():
    with pytest.raises(SystemExit) as excinfo:
        deezer2am.main(["--csv"])

    assert excinfo.value.code == 2


def test_cli_csv_and_json_are_exclusive():
    with pytest.raises(SystemExit) as excinfo:
        deezer2am.main(["1", "--csv", "--json"])

    assert excinfo.value.code == 2


def merged_tracks_response():
    """A get_playlist_tracks response as saved by --json: all pages merged, no "next"."""
    response = fixture("playlist_tracks_page1")
    response["data"] += fixture("playlist_tracks_page2")["data"]
    del response["next"]
    return response


def write_json(tmp_path, content):
    path = tmp_path / "playlist.json"
    path.write_text(json.dumps(content))
    return path


def test_cli_from_json_prints_tracks_as_csv_without_calling_api(api, tmp_path, capsys):
    path = write_json(tmp_path, merged_tracks_response())

    deezer2am.main(["--from-json", str(path)])

    header, *rows = csv.reader(io.StringIO(capsys.readouterr().out))
    assert header == deezer2am.CSV_HEADER
    assert [row[16] for row in rows] == ["XXA011500001", "XXB016900001"]
    assert rows[0][1] == "Morning Light (Remastered 2015)"
    assert len(api.calls) == 0


def test_cli_from_json_matches_csv_output(api, tmp_path, capsys):
    mock_paginated_tracks(api)
    deezer2am.main(["3333333333", "--csv"])
    from_api = capsys.readouterr().out
    path = write_json(tmp_path, merged_tracks_response())

    deezer2am.main(["--from-json", str(path)])

    assert capsys.readouterr().out == from_api


def test_cli_from_json_does_not_need_user_id(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("DEEZER_USER_ID")
    path = write_json(tmp_path, merged_tracks_response())

    deezer2am.main(["--from-json", str(path)])

    assert len(capsys.readouterr().out.splitlines()) == 3


def test_cli_from_json_reads_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(merged_tracks_response())))

    deezer2am.main(["3333333333", "--from-json", "-"])

    assert len(capsys.readouterr().out.splitlines()) == 3


def test_cli_from_json_of_empty_playlist_prints_header_only(tmp_path, capsys):
    path = write_json(tmp_path, {"data": [], "total": 0})

    deezer2am.main(["--from-json", str(path)])

    assert capsys.readouterr().out == ",".join(deezer2am.CSV_HEADER) + "\n"


def test_load_playlist_tracks_warns_about_single_page(tmp_path):
    path = write_json(tmp_path, fixture("playlist_tracks_page1"))
    messages = []
    sink_id = logger.add(messages.append, level="WARNING", format="{level} {message}")

    try:
        tracks = deezer2am.load_playlist_tracks(path)
    finally:
        logger.remove(sink_id)

    assert [t["id"] for t in tracks] == [900000001]
    assert len(messages) == 1
    assert "single page of the playlist (1 of 2 tracks)" in messages[0]


def test_load_playlist_tracks_raises_api_error(tmp_path):
    path = write_json(tmp_path, fixture("error_no_data"))

    with pytest.raises(DeezerError) as excinfo:
        deezer2am.load_playlist_tracks(path)

    assert excinfo.value.code == 800


@pytest.mark.parametrize("content", [[], {"total": 0}, {"data": {}}],
                         ids=["list", "no data", "data not a list"])
def test_load_playlist_tracks_rejects_other_json(tmp_path, content):
    path = write_json(tmp_path, content)

    with pytest.raises(ValueError, match="not a get_playlist_tracks response"):
        deezer2am.load_playlist_tracks(path)


@pytest.mark.parametrize("content", [None, "not json"], ids=["missing file", "invalid JSON"])
def test_cli_from_json_bad_file_exits_with_status_1(tmp_path, capsys, content):
    path = tmp_path / "playlist.json"
    if content is not None:
        path.write_text(content)

    with pytest.raises(SystemExit) as excinfo:
        deezer2am.main(["--from-json", str(path)])

    assert excinfo.value.code == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("argv", [["--json", "--from-json", "x.json"], ["--from-json", "-"]],
                         ids=["--json", "stdin without playlist_id"])
def test_cli_from_json_bad_arguments(argv):
    with pytest.raises(SystemExit) as excinfo:
        deezer2am.main(argv)

    assert excinfo.value.code == 2


def tracks_with_missing_data():
    """A --json response whose 2nd track has no ISRC and whose 3rd has no artist nor album."""
    response = merged_tracks_response()
    no_isrc = dict(response["data"][1], isrc="")
    bare = {"id": 1, "title": "Bare track", "link": "https://www.deezer.com/track/1",
            "isrc": "FRXXX0000001", "duration": 60}
    response["data"] = [response["data"][0], no_isrc, bare]
    response["total"] = 3
    return response


def read_report(path):
    return json.loads(path.read_text())


def test_missing_fields_of_complete_track_is_empty():
    assert deezer2am.missing_fields(fixture("track")) == []


@pytest.mark.parametrize("change, missing", [
    ({"isrc": ""}, ["isrc"]),
    ({"isrc": None}, ["isrc"]),
    ({"title": "  "}, ["title"]),
    ({"artist": {"id": 1}}, ["artist.name"]),
    ({"album": None}, ["album.title"]),
    ({"title": None, "isrc": None}, ["title", "isrc"]),
], ids=["empty isrc", "null isrc", "blank title", "no artist name", "no album", "several"])
def test_missing_fields(change, missing):
    track = fixture("track") | change

    assert deezer2am.missing_fields(track) == missing


def test_missing_fields_of_absent_keys():
    assert deezer2am.missing_fields({"id": 1}) == deezer2am.REQUIRED_FIELDS


def test_csv_row_of_track_missing_data_has_empty_columns():
    row = deezer2am.track_to_csv_row({"id": 1, "title": "Bare track"})

    assert len(row) == len(deezer2am.CSV_HEADER)
    assert row[1] == "Bare track"
    assert row[3] == row[4] == row[5] == row[7] == row[12] == row[16] == ""


def test_missing_data_report_lists_tracks_and_missing_fields():
    tracks = tracks_with_missing_data()["data"]

    report = deezer2am.missing_data_report(tracks, "3333333333", "Deezer API")

    assert report == {
        "playlist_id": "3333333333",
        "source": "Deezer API",
        "total_tracks": 3,
        "tracks_with_missing_data": 2,
        "tracks": [
            {"position": 2, "id": 900000002, "link": "https://www.deezer.com/track/900000002",
             "title": "Paper Boats", "artist": "Harbor Lights", "album": "Paper Boats", "isrc": "",
             "missing": ["isrc"]},
            {"position": 3, "id": 1, "link": "https://www.deezer.com/track/1",
             "title": "Bare track", "artist": None, "album": None, "isrc": "FRXXX0000001",
             "missing": ["artist.name", "album.title"]},
        ],
    }


def test_missing_data_report_is_none_when_nothing_misses():
    tracks = merged_tracks_response()["data"]

    assert deezer2am.missing_data_report(tracks, "3333333333", "Deezer API") is None


def test_cli_csv_writes_missing_data_report_named_after_playlist(api, tmp_path, capsys):
    response = tracks_with_missing_data()
    api.get(f"{API}/playlist/3333333333/tracks", json=response)

    deezer2am.main(["3333333333", "--csv"])

    header, *rows = csv.reader(io.StringIO(capsys.readouterr().out))
    assert len(rows) == 3  # tracks missing data are still written to the CSV
    report = read_report(tmp_path / "playlist-3333333333-missing-data.json")
    assert report["source"] == "Deezer API"
    assert [(t["position"], t["missing"]) for t in report["tracks"]] == [
        (2, ["isrc"]), (3, ["artist.name", "album.title"])]


def test_cli_csv_writes_no_report_when_nothing_misses(api, tmp_path):
    mock_paginated_tracks(api)

    deezer2am.main(["3333333333", "--csv"])

    assert list(tmp_path.glob("*-missing-data.json")) == []


def test_cli_without_csv_writes_no_report(api, tmp_path):
    api.get(f"{API}/playlist/3333333333/tracks", json=tracks_with_missing_data())

    deezer2am.main(["3333333333", "--json"])

    assert list(tmp_path.glob("*-missing-data.json")) == []


def test_cli_report_dir(api, tmp_path):
    api.get(f"{API}/playlist/3333333333/tracks", json=tracks_with_missing_data())

    deezer2am.main(["3333333333", "--csv", "--report-dir", "reports/deezer"])

    assert (tmp_path / "reports/deezer/playlist-3333333333-missing-data.json").exists()


def test_cli_from_json_report_is_named_after_file(tmp_path):
    path = tmp_path / "playlist-3333333333.json"
    path.write_text(json.dumps(tracks_with_missing_data()))

    deezer2am.main(["--from-json", str(path)])

    report = read_report(tmp_path / "playlist-3333333333-missing-data.json")
    assert report["playlist_id"] is None
    assert report["source"] == str(path)
    assert report["tracks_with_missing_data"] == 2


def test_cli_from_json_report_is_named_after_given_playlist_id(api, tmp_path):
    path = write_json(tmp_path, tracks_with_missing_data())

    deezer2am.main(["4444444444", "--from-json", str(path)])

    report = read_report(tmp_path / "playlist-4444444444-missing-data.json")
    assert report["playlist_id"] == "4444444444"
    assert len(api.calls) == 0


def test_cli_from_stdin_report_is_named_after_playlist_id(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(tracks_with_missing_data())))

    deezer2am.main(["4444444444", "--from-json", "-"])

    assert read_report(tmp_path / "playlist-4444444444-missing-data.json")["source"] == "-"


def test_cli_missing_data_is_logged(api, capsys):
    api.get(f"{API}/playlist/3333333333/tracks", json=tracks_with_missing_data())

    deezer2am.main(["3333333333", "--csv"])

    assert ("WARNING | 2 of 3 tracks miss data required by convertsongs.py, "
            "see playlist-3333333333-missing-data.json") in capsys.readouterr().err
