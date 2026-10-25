"""Characterization tests of convertsongs.py, against mocked Apple Music responses.

They pin down what the script does today, known issues included (see
docs/convertsongs.md), so that a refactoring changing its behavior makes a test
fail. Tests pinning a known issue say so: when fixing one, update its test.
"""

import csv
import importlib
import json
import runpy
import sys
from pathlib import Path

import pytest
import requests
import responses
from ratelimit import RateLimitDecorator
from responses import matchers

from deezer2am import CSV_HEADER
from helpers import FIXTURES

SCRIPT = Path(__file__).parent.parent / "convertsongs.py"
AMP = "https://amp-api.music.apple.com/v1"
ITUNES = "https://itunes.apple.com/search"
CREDENTIALS = {
    "token.dat": "Bearer test-token",
    "media_user_token.dat": "test-media-user-token",
    "cookies.dat": "media-user-token=test; itspod=1",
    "country_code.dat": "fr",
}
PLAYLIST_ID = "p.qQXLxPLtA75zg8"  # "My playlist" in library_playlists.json


def apple(name):
    path = FIXTURES / "apple" / name
    return path.read_text() if path.suffix == ".html" else json.loads(path.read_text())


def write_credentials(directory):
    for name, value in CREDENTIALS.items():
        (directory / name).write_text(value + "\n")


@pytest.fixture(scope="session")
def convertsongs(tmp_path_factory):
    """Import convertsongs.py, which checks sys.argv and reads its credentials at import."""
    directory = tmp_path_factory.mktemp("credentials")
    write_credentials(directory)
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(directory)
        patch.setattr(sys, "argv", ["convertsongs.py", "playlist.csv"])
        patch.setattr("builtins.input", lambda prompt: pytest.fail(f"prompted: {prompt}"))
        return importlib.import_module("convertsongs")


@pytest.fixture
def cs(convertsongs, monkeypatch):
    """convertsongs, with its rate limit reset and its sleeps recorded (in cs.sleeps)."""
    limiter = next(cell.cell_contents for cell in convertsongs.call_api.__closure__
                   if isinstance(cell.cell_contents, RateLimitDecorator))
    monkeypatch.setattr(limiter, "num_calls", 0)
    monkeypatch.setattr(limiter, "last_reset", limiter.clock())
    sleeps = []
    monkeypatch.setattr(convertsongs, "sleep", sleeps.append)
    monkeypatch.setattr(convertsongs, "sleeps", sleeps, raising=False)
    return convertsongs


@pytest.fixture
def session():
    return requests.Session()


# Builders of Apple responses and mocks -------------------------------------------------

def catalog_song(song_id, album, artist, name="Song"):
    return {"id": song_id, "type": "songs",
            "attributes": {"name": name, "artistName": artist, "albumName": album}}


def itunes_result(track_id, track, artist, album):
    return {"wrapperType": "track", "kind": "song", "trackId": track_id, "trackName": track,
            "artistName": artist, "collectionName": album,
            "trackViewUrl": f"https://music.apple.com/fr/album/{track_id}?i={track_id}"}


def mock_isrc(api, isrc, songs, status=200):
    api.get(f"{AMP}/catalog/fr/songs?filter[isrc]={isrc}", json={"data": songs}, status=status)


def mock_search(api, term, results, artist=None, album=None, status=200):
    params = {"country": "fr", "media": "music", "entity": "song", "limit": "15", "term": term}
    if artist is not None:
        params["artistTerm"] = artist
    if album is not None:
        params["albumTerm"] = album
    api.get(ITUNES, json={"resultCount": len(results), "results": results}, status=status,
            match=[matchers.query_param_matcher(params)])


def mock_page(api, result, body=None, status=200):
    """The web page verify_release_date downloads for a search result."""
    api.get(result["trackViewUrl"], body=body or "<html></html>", status=status)


def mock_equivalent(api, song_id, equivalent=None):
    api.get(f"{AMP}/catalog/fr/songs?filter[equivalents]={song_id}",
            json={"data": [{"id": equivalent or song_id, "type": "songs"}]})


def mock_add(api, song_id, playlist_id=PLAYLIST_ID, status=204):
    api.post(f"{AMP}/me/library/playlists/{playlist_id}/tracks", status=status,
             match=[matchers.json_params_matcher({"data": [{"id": song_id, "type": "songs"}]})])


def write_playlist_csv(path, rows):
    """Write a CSV in the format of convertsongs.py; rows are dicts of the columns it reads."""
    columns = {"title": 1, "artist": 3, "album": 5, "album_artist": 7, "date": 8, "isrc": 16}
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(CSV_HEADER)
        for values in rows:
            row = [""] * len(CSV_HEADER)
            for name, value in values.items():
                row[columns[name]] = value
            writer.writerow(row)
    return path


# Start-up ----------------------------------------------------------------------------

def test_credentials_are_read_from_dat_files(cs):
    assert cs.token == "Bearer test-token"
    assert cs.media_user_token == "test-media-user-token"
    assert cs.cookies == "media-user-token=test; itspod=1"
    assert cs.country_code == "fr"


def test_get_connection_data_prompts_when_file_is_missing(cs, monkeypatch, tmp_path):
    monkeypatch.setattr("builtins.input", lambda prompt: f"typed after {prompt!r}")

    assert cs.get_connection_data(tmp_path / "none.dat", "Token?") == "typed after 'Token?'"


def test_without_argument_prints_usage_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["convertsongs.py"])

    with pytest.raises(SystemExit):
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert "uv run convertsongs.py yourplaylist.csv" in capsys.readouterr().out


# create_apple_music_playlist -----------------------------------------------------------

def test_existing_playlist_is_reused(cs, api, session):
    api.get(f"{AMP}/me/library/playlists", json=apple("library_playlists.json"))

    assert cs.create_apple_music_playlist(session, "My playlist") == PLAYLIST_ID
    assert cs.sleeps == []


def test_playlist_name_must_match_exactly(cs, api, session):
    api.get(f"{AMP}/me/library/playlists", json=apple("library_playlists.json"))
    api.post(f"{AMP}/me/library/playlists", status=201,
             json=apple("library_playlist_created.json"))

    assert cs.create_apple_music_playlist(session, "my playlist") == "p.NEWxPLtA75zg8"


def test_missing_playlist_is_created(cs, api, session):
    api.get(f"{AMP}/me/library/playlists", json={"data": []})
    api.post(f"{AMP}/me/library/playlists", status=201,
             json=apple("library_playlist_created.json"),
             match=[matchers.json_params_matcher({"attributes": {
                 "name": "New playlist",
                 "description": "A new playlist created via API using Spotify-2-AppleMusic"}})])

    assert cs.create_apple_music_playlist(session, "New playlist") == "p.NEWxPLtA75zg8"
    assert cs.sleeps == [0.2]


def test_playlists_listing_error_still_creates_playlist(cs, api, session):
    api.get(f"{AMP}/me/library/playlists", status=500)
    api.post(f"{AMP}/me/library/playlists", status=201,
             json=apple("library_playlist_created.json"))

    assert cs.create_apple_music_playlist(session, "New playlist") == "p.NEWxPLtA75zg8"


@pytest.mark.parametrize("status, message", [
    (401, "Error 401: Unauthorized"), (403, "Error 403: Forbidden")])
def test_playlist_creation_auth_error_exits(cs, api, session, capsys, status, message):
    api.get(f"{AMP}/me/library/playlists", status=status)
    api.post(f"{AMP}/me/library/playlists", status=status)

    with pytest.raises(SystemExit) as excinfo:
        cs.create_apple_music_playlist(session, "New playlist")

    assert excinfo.value.code == 1
    assert message in capsys.readouterr().out


def test_playlist_creation_bad_request_prints_apple_errors(cs, api, session, capsys):
    api.get(f"{AMP}/me/library/playlists", json={"data": []})
    api.post(f"{AMP}/me/library/playlists", status=400, json={"errors": [{
        "code": "40000", "title": "Invalid Request", "detail": "Name is too long",
        "messageForDisplay": "Invalid name"}]})

    with pytest.raises(SystemExit) as excinfo:
        cs.create_apple_music_playlist(session, "New playlist")

    assert excinfo.value.code == 1
    output = capsys.readouterr().out
    assert "40000: Invalid name" in output
    assert "Invalid Request: Name is too long" in output


def test_playlist_creation_other_error_raises(cs, api, session):
    api.get(f"{AMP}/me/library/playlists", json={"data": []})
    api.post(f"{AMP}/me/library/playlists", status=500)

    with pytest.raises(Exception, match="Error 500 while creating playlist New playlist"):
        cs.create_apple_music_playlist(session, "New playlist")


# get_playlist_track_ids ----------------------------------------------------------------

def test_playlist_track_ids_are_catalog_ids(cs, api, session):
    api.get(f"{AMP}/me/library/playlists/{PLAYLIST_ID}/tracks",
            json=apple("library_playlist_tracks.json"))

    assert cs.get_playlist_track_ids(session, PLAYLIST_ID) == ["1500000001"]


def test_playlist_track_ids_of_empty_playlist(cs, api, session):
    # Apple answers 404 for the tracks of a playlist without tracks
    api.get(f"{AMP}/me/library/playlists/{PLAYLIST_ID}/tracks", status=404)

    assert cs.get_playlist_track_ids(session, PLAYLIST_ID) == []


def test_playlist_track_ids_error_raises(cs, api, session):
    api.get(f"{AMP}/me/library/playlists/{PLAYLIST_ID}/tracks", status=500)

    with pytest.raises(Exception, match=f"Error while getting playlist {PLAYLIST_ID}!"):
        cs.get_playlist_track_ids(session, PLAYLIST_ID)


# ISRC search: match_isrc_to_itunes_id -------------------------------------------------

def test_isrc_search_picks_the_song_of_the_csv_album(cs, api, session):
    mock_isrc(api, "XXA011500001", apple("catalog_songs_isrc.json")["data"])

    song_id = cs.match_isrc_to_itunes_id(
        session, "the lanterns live", "the lanterns", "XXA011500001")

    assert song_id == "1900000002"


@pytest.mark.parametrize("album, album_artist", [
    ("Lantern Songs (Remastered)", "The Lanterns"),     # rule 1: album and artist equal
    ("lantern songs (remastered)", "Lanterns"),          # rule 2: album equal, artist contained
    ("Lantern Songs (Remastered)", "The Lanterns & Co"),  # rule 2: artist containing
    ("LanternXXX", "The LanXXX"),           # rule 3: first 7 characters equal
    ("Lantern Songs (Remastered)", "Someone else"),     # rule 4: album equal
], ids=["exact", "artist contained", "artist containing", "7 char prefixes", "album only"])
def test_isrc_search_rules(cs, api, session, album, album_artist):
    mock_isrc(api, "XXA011500001", [catalog_song("1", "Lantern Songs (Remastered)", "The Lanterns")])

    assert cs.match_isrc_to_itunes_id(session, album, album_artist, "XXA011500001") == "1"


@pytest.mark.parametrize("album, album_artist", [
    ("LanterX Songs (Remastered)", "The LanXerns"),  # album: 6 first characters equal, artist: 7
    ("LanternXSongs (Remastered)", "The LaXterns"),  # album: 7, artist: 6
], ids=["album", "artist"])
def test_isrc_search_needs_7_char_prefixes(cs, api, session, album, album_artist):
    mock_isrc(api, "XXA011500001", [catalog_song("1", "Lantern Songs (Remastered)", "The Lanterns")])

    assert cs.match_isrc_to_itunes_id(session, album, album_artist, "XXA011500001") is None


def test_isrc_search_rejects_song_of_another_album(cs, api, session):
    mock_isrc(api, "XXA011500001", apple("catalog_songs_isrc.json")["data"])

    assert cs.match_isrc_to_itunes_id(session, "Morning Light", "The Lanterns", "XXA011500001") is None


def test_isrc_search_first_candidate_passing_any_rule_wins(cs, api, session):
    # The 1st candidate only passes rule 4 (album), the 2nd rule 1 (album and artist)
    mock_isrc(api, "X", [catalog_song("1", "Album", "Cover band"),
                         catalog_song("2", "Album", "Artist")])

    assert cs.match_isrc_to_itunes_id(session, "Album", "Artist", "X") == "1"


def test_isrc_search_compares_escaped_apostrophes(cs, api, session):
    mock_isrc(api, "X", [catalog_song("1", "Rock 'n' Roll", "Artist")])

    # convertsongs passes the CSV values escaped by escape_apostrophes
    assert cs.match_isrc_to_itunes_id(session, "rock \\'n\\' roll", "artist", "X") == "1"


def test_isrc_search_without_result(cs, api, session):
    mock_isrc(api, "X", [])

    assert cs.match_isrc_to_itunes_id(session, "Album", "Artist", "X") is None


def test_isrc_search_error_is_printed_and_swallowed(cs, api, session, capsys):
    # Known issue: an expired token silently turns every track into a text search
    mock_isrc(api, "X", [], status=401)

    assert cs.match_isrc_to_itunes_id(session, "Album", "Artist", "X") is None
    assert "An error occured with the ISRC based search request: Error 401" in (
        capsys.readouterr().out)


def test_isrc_search_with_empty_album_accepts_first_song(cs, api, session):
    # Known issue: rule 3 compares with "" prefixes, which every name starts with
    mock_isrc(api, "X", [catalog_song("1", "Anything", "Anyone")])

    assert cs.match_isrc_to_itunes_id(session, "", "", "X") == "1"


def test_isrc_search_session_headers_are_sent(cs, api, tmp_path):
    # create_playlist_and_add_song sets the headers of the Apple Music web player
    # (the cookies encoded in UTF-8)
    headers = {"Authorization": "Bearer test-token", "media-user-token": "test-media-user-token",
               "Cookie": b"media-user-token=test; itspod=1", "Origin": "https://music.apple.com"}
    api.get(f"{AMP}/me/library/playlists", json=apple("library_playlists.json"),
            match=[matchers.header_matcher(headers)])
    api.get(f"{AMP}/me/library/playlists/{PLAYLIST_ID}/tracks", status=404,
            match=[matchers.header_matcher(headers)])

    cs.create_playlist_and_add_song(write_playlist_csv(tmp_path / "My_playlist.csv", []))


# Text search: get_itunes_id and try_to_match -------------------------------------------

def test_text_search_matches_title_artist_and_album(cs, api):
    single, album = apple("itunes_search.json")["results"]
    mock_search(api, "Paper Boats", [album, single], artist="Harbor Lights", album="Paper Boats")

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Paper Boats", "") == 1900000004


def test_text_search_picks_single_listed_before_album(cs, api):
    # The single (title and artist equal, rule 3) comes before the album version (rule 1)
    single, album = apple("itunes_search.json")["results"]
    mock_search(api, "Paper Boats", [single, album], artist="Harbor Lights", album="Paper Boats")
    mock_page(api, single, status=404)  # it fails rule 1, so rule 2 fetches its page

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Paper Boats", "") == 1900000003


@pytest.mark.parametrize("track, artist", [
    ("Paper Boats", "Harbor Lights"),          # rule 3: title and artist equal
    ("paper boats", "HARBOR LIGHTS"),          # rule 3, case insensitive
    ("Paper Boats", "HarborLights"),         # rule 4: artist equal without spaces
    ("Paper Boats", "Harbor Lights feat. X"),  # rule 4: artist contained
], ids=["exact", "case", "spaces", "artist contained"])
def test_text_search_rules(cs, api, track, artist):
    result = itunes_result(1, track, artist, "Other album")
    mock_search(api, "Paper Boats", [result], artist="Harbor Lights", album="Album")
    mock_page(api, result, status=404)

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Album", "") == 1


def test_text_search_rule_5_compares_swapped_fields(cs, api):
    # Known issue: rule 5 compares the result's artist with the CSV title
    result = itunes_result(1, "Harbor Lights", "Paper Boats", "Other album")
    mock_search(api, "Paper Boats", [result], artist="Harbor Lights", album="Album")
    mock_page(api, result, status=404)

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Album", "") == 1


def test_text_search_title_and_album_only_is_no_match(cs, api):
    result = itunes_result(1, "Paper Boats", "Someone else", "Album")
    for artist, album in [("Harbor Lights", "Album"), ("Harbor Lights", None), (None, "Album"),
                          (None, None)]:
        mock_search(api, "Paper Boats", [result], artist=artist, album=album)

    # The page of the result is fetched by every query, so 4 times
    mock_page(api, result, status=404)

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Album", "") is None
    assert len([c for c in api.calls if c.request.url == result["trackViewUrl"]]) == 4


def test_text_search_cascade_stops_at_first_match(cs, api):
    result = itunes_result(1, "Paper Boats", "Harbor Lights", "Album")
    mock_search(api, "Paper Boats", [], artist="Harbor Lights", album="Album")
    mock_search(api, "Paper Boats", [result], artist="Harbor Lights")

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Album", "") == 1
    assert len(api.calls) == 2


def test_text_search_sends_four_queries_before_giving_up(cs, api):
    mock_search(api, "Paper Boats", [], artist="Harbor Lights", album="Album")
    mock_search(api, "Paper Boats", [], artist="Harbor Lights")
    mock_search(api, "Paper Boats", [], album="Album")
    mock_search(api, "Paper Boats", [])

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Album", "") is None
    assert len(api.calls) == 4


def test_text_search_first_result_passing_any_rule_wins(cs, api):
    # The 1st result passes rule 3 (title and artist), the 2nd rule 1 (and album)
    first = itunes_result(1, "Paper Boats", "Harbor Lights", "Compilation")
    second = itunes_result(2, "Paper Boats", "Harbor Lights", "Album")
    mock_search(api, "Paper Boats", [first, second], artist="Harbor Lights", album="Album")
    mock_page(api, first, status=404)

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Album", "") == 1


def test_text_search_matches_release_date(cs, api):
    # Rule 2: the date of the page footer equals the CSV date, whatever the names
    result = itunes_result(1, "Bateaux de papier", "Harbor Lights (FR)", "Album")
    mock_search(api, "Paper Boats", [result], artist="Harbor Lights", album="Album")
    mock_page(api, result, body=apple("song_page.html"))

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Album", "1969-01-01") == 1


def test_text_search_fetches_pages_even_without_date(cs, api):
    # Known issue: rule 2 downloads the page of every result failing rule 1, even when
    # the CSV has no date (as Deezer CSVs) and the dates can't be compared
    results = [itunes_result(i, f"Other {i}", "Other", "Other") for i in range(3)]
    mock_search(api, "Paper Boats", results, artist="Harbor Lights", album="Album")
    mock_search(api, "Paper Boats", [], artist="Harbor Lights")
    mock_search(api, "Paper Boats", [], album="Album")
    mock_search(api, "Paper Boats", [])
    for result in results:
        mock_page(api, result, body=apple("song_page.html"))

    assert cs.get_itunes_id("Paper Boats", "Harbor Lights", "Album", "") is None


def test_text_search_of_escaped_apostrophes_does_not_match(cs, api):
    # Known issue: CSV values are escaped (\') before the search, iTunes values aren't
    title = "It\\'s Getting Late"  # as escape_apostrophes passes it
    result = itunes_result(1, "It's Getting Late", "Marble Fern", "Low Tide")
    for artist, album in [("Marble Fern", "Low Tide"), ("Marble Fern", None),
                          (None, "Low Tide"), (None, None)]:
        mock_search(api, title, [result], artist=artist, album=album)
    mock_page(api, result, status=404)

    assert cs.get_itunes_id(title, "Marble Fern", "Low Tide", "") is None


# call_api ------------------------------------------------------------------------------

def test_call_api_returns_json(cs, api):
    api.get(ITUNES, json={"resultCount": 0, "results": []})

    assert cs.call_api(ITUNES) == {"resultCount": 0, "results": []}


def test_call_api_404_gives_no_result(cs, api):
    api.get(ITUNES, status=404)

    assert cs.call_api(ITUNES) == {"results": []}
    assert len(api.calls) == 1


def test_call_api_retries_3_times_without_waiting(cs, api):
    api.get(ITUNES, status=503)

    assert cs.call_api(ITUNES) == {"results": []}
    assert len(api.calls) == 3
    assert cs.sleeps == []


def test_call_api_rate_limit_exits(cs, api, capsys):
    # Known issue: 19 calls per second (not per minute), and exceeding it exits
    api.get(ITUNES, json={"results": []})

    for _ in range(19):
        cs.try_to_match(ITUNES, "Title", "Artist", "Album", "")
    with pytest.raises(SystemExit) as excinfo:
        cs.try_to_match(ITUNES, "Title", "Artist", "Album", "")

    assert excinfo.value.code == 1
    assert "too many calls" in capsys.readouterr().out


# verify_release_date -------------------------------------------------------------------

@pytest.mark.parametrize("date, expected", [
    ("1969-01-01", True), ("January 1, 1969", True), ("1969-06-01", False), ("", False)])
def test_verify_release_date(cs, api, date, expected):
    result = itunes_result(1, "Paper Boats", "Harbor Lights", "Album")
    mock_page(api, result, body=apple("song_page.html"))

    assert cs.verify_release_date(result, date) is expected


@pytest.mark.parametrize("body, status", [
    ("<html><p>1 janvier 1969</p></html>", 200), (None, 404)],
    ids=["no footer", "page error"])
def test_verify_release_date_without_footer(cs, api, body, status):
    result = itunes_result(1, "Paper Boats", "Harbor Lights", "Album")
    mock_page(api, result, body=body, status=status)

    assert cs.verify_release_date(result, "1969-01-01") is False


# Adding a song: fetch_equivalent_song_id and add_song_to_playlist -------------------------

def test_equivalent_song_id(cs, api, session):
    mock_equivalent(api, "1", "2")

    assert cs.fetch_equivalent_song_id(session, "1") == "2"


@pytest.mark.parametrize("kwargs", [{"status": 404}, {"json": {"data": []}}],
                         ids=["error", "no equivalent"])
def test_equivalent_song_id_defaults_to_song_id(cs, api, session, kwargs):
    api.get(f"{AMP}/catalog/fr/songs?filter[equivalents]=1", **kwargs)

    assert cs.fetch_equivalent_song_id(session, "1") == "1"


@pytest.mark.parametrize("status", [200, 201, 204])
def test_add_song(cs, api, session, status):
    mock_equivalent(api, "1")
    mock_add(api, "1", status=status)

    assert cs.add_song_to_playlist(session, 1, PLAYLIST_ID, [], "My playlist") == "OK"


def test_add_song_adds_its_equivalent(cs, api, session, capsys):
    mock_equivalent(api, "1", "2")
    mock_add(api, "2")

    assert cs.add_song_to_playlist(session, "1", PLAYLIST_ID, [], "My playlist") == "OK"
    assert "1 switched to equivalent -> 2" in capsys.readouterr().out


def test_add_song_whose_equivalent_is_in_playlist(cs, api, session):
    mock_equivalent(api, "1", "2")

    assert cs.add_song_to_playlist(session, "1", PLAYLIST_ID, ["2"], "My playlist") == (
        "DUPLICATE")


def test_add_song_error(cs, api, session):
    mock_equivalent(api, "1")
    mock_add(api, "1", status=500)

    assert cs.add_song_to_playlist(session, "1", PLAYLIST_ID, [], "My playlist") == "ERROR"


def test_add_song_connection_error(cs, api, session, capsys):
    mock_equivalent(api, "1")
    api.post(f"{AMP}/me/library/playlists/{PLAYLIST_ID}/tracks",
             body=requests.ConnectionError("blocked"))

    assert cs.add_song_to_playlist(session, "1", PLAYLIST_ID, [], "My playlist") == "ERROR"
    assert "HOST ERROR" in capsys.readouterr().out


# create_playlist_and_add_song ----------------------------------------------------------

def mock_playlist(api, tracks=None):
    """"My playlist" exists, holding tracks (library_playlist_tracks.json by default)."""
    api.get(f"{AMP}/me/library/playlists", json=apple("library_playlists.json"))
    api.get(f"{AMP}/me/library/playlists/{PLAYLIST_ID}/tracks",
            json=tracks or apple("library_playlist_tracks.json"))


def mock_not_found(api, title, artist, album, isrc):
    mock_isrc(api, isrc, [])
    for artist_term, album_term in [(artist, album), (artist, None), (None, album), (None, None)]:
        mock_search(api, title, [], artist=artist_term, album=album_term)


def test_convert_playlist(cs, api, tmp_path, capsys):
    path = write_playlist_csv(tmp_path / "My_playlist.csv", [
        # Found by ISRC
        {"title": "Morning Light (Remastered 2015)", "artist": "The Lanterns",
         "album": "Lantern Songs (Remastered)", "album_artist": "The Lanterns", "isrc": "XXA011500001"},
        # Not found by ISRC, found by text search (the single, see itunes_search.json)
        {"title": "Paper Boats", "artist": "Harbor Lights", "album": "Paper Boats",
         "album_artist": "Harbor Lights", "isrc": "XXB016900001"},
        # Not found
        {"title": "Unknown", "artist": "Nobody", "album": "Nothing",
         "album_artist": "Nobody", "isrc": "XX0000000000"},
        # Found by ISRC, already in the playlist
        {"title": "Already there", "artist": "Some Artist", "album": "Some Album",
         "album_artist": "Some Artist", "isrc": "XX0000000001"},
    ])
    mock_playlist(api)
    mock_isrc(api, "XXA011500001", apple("catalog_songs_isrc.json")["data"])
    mock_equivalent(api, "1900000001")
    mock_add(api, "1900000001")
    mock_isrc(api, "XXB016900001", [])
    results = apple("itunes_search.json")["results"]
    mock_search(api, "Paper Boats", results, artist="Harbor Lights", album="Paper Boats")
    mock_page(api, results[0], status=404)
    mock_equivalent(api, "1900000003")
    mock_add(api, "1900000003")
    mock_not_found(api, "Unknown", "Nobody", "Nothing", "XX0000000000")
    mock_isrc(api, "XX0000000001", [catalog_song("1500000001", "Some Album", "Some Artist")])

    cs.create_playlist_and_add_song(str(path))

    output = capsys.readouterr().out
    assert "N°1 | Morning Light (Remastered 2015) | The Lanterns | Lantern Songs (Remastered) => 1900000001" in output
    assert "N°2 | Paper Boats | Harbor Lights | Paper Boats => 1900000003" in output
    assert "N°3 | Unknown | Nobody | Nothing => NOT FOUND" in output
    assert "Song 1500000001 already in playlist My playlist!" in output
    assert ("\n - STAT REPORT -\nPlaylist Songs: 4\nConverted Songs: 2\nFailed Songs: 2\n"
            "Playlist converted at 50%\n\nConverted using ISRC: 2\n"
            "Converted using text based search: 1\n") in output
    assert (tmp_path / "My playlist_noresult.txt").read_text() == (
        "Unknown | Nobody | Nothing => NOT FOUND\n\n")
    # Added tracks: max(delay, 0.5) before adding, delay after; skipped duplicate: none
    assert cs.sleeps == [1, 1, 1, 1, 1]


def test_convert_playlist_name_comes_from_file_name(cs, api, tmp_path):
    api.get(f"{AMP}/me/library/playlists", json={"data": []})
    api.post(f"{AMP}/me/library/playlists", status=201,
             json=apple("library_playlist_created.json"),
             match=[matchers.json_params_matcher({"attributes": {
                 "name": "My road trip",
                 "description": "A new playlist created via API using Spotify-2-AppleMusic"}})])
    api.get(f"{AMP}/me/library/playlists/p.NEWxPLtA75zg8/tracks", status=404)

    cs.create_playlist_and_add_song(str(write_playlist_csv(tmp_path / "My_Road_Trip.v2.csv", [])))


def test_convert_empty_playlist_reports_100_percent(cs, api, tmp_path, capsys):
    mock_playlist(api)

    cs.create_playlist_and_add_song(str(write_playlist_csv(tmp_path / "My_playlist.csv", [])))

    assert "Playlist Songs: 0\nConverted Songs: 0\nFailed Songs: 0\n" \
           "Playlist converted at 100%" in capsys.readouterr().out


def test_convert_playlist_with_bad_header(cs, api, tmp_path, capsys):
    # The playlist is looked up (or created) before the header is checked
    mock_playlist(api)
    path = tmp_path / "My_playlist.csv"
    path.write_text("Name,Artist,Album\nMorning Light,The Lanterns,1\n")

    cs.create_playlist_and_add_song(str(path))

    output = capsys.readouterr().out
    assert "The CSV file is not in the correct format!" in output
    assert "STAT REPORT" not in output


def test_convert_playlist_escapes_apostrophes_in_isrc_search(cs, api, tmp_path, capsys):
    path = write_playlist_csv(tmp_path / "My_playlist.csv", [
        {"title": "It's Getting Late", "artist": "Marble Fern", "album": "Low Tide",
         "album_artist": "Marble Fern", "isrc": "XXC010600001"}])
    mock_playlist(api)
    mock_isrc(api, "XXC010600001", [catalog_song("1", "Low Tide", "Marble Fern")])
    mock_equivalent(api, "1")
    mock_add(api, "1")

    cs.create_playlist_and_add_song(str(path))

    assert "N°1 | It\\'s Getting Late | Marble Fern | Low Tide => 1" in (
        capsys.readouterr().out)


def test_convert_playlist_adds_repeated_track_twice(cs, api, tmp_path):
    # Known issue: the playlist's track ids aren't updated as tracks are added
    row = {"title": "Song", "artist": "Artist", "album": "Album", "album_artist": "Artist",
           "isrc": "X"}
    path = write_playlist_csv(tmp_path / "My_playlist.csv", [row, row])
    mock_playlist(api)
    mock_isrc(api, "X", [catalog_song("1", "Album", "Artist")])
    mock_equivalent(api, "1")
    mock_add(api, "1")

    cs.create_playlist_and_add_song(str(path))

    adds = [c for c in api.calls if c.request.method == "POST"]
    assert len(adds) == 2


def test_convert_playlist_add_error_is_written_to_noresult_file(cs, api, tmp_path, capsys):
    path = write_playlist_csv(tmp_path / "My_playlist.csv", [
        {"title": "Song", "artist": "Artist", "album": "Album", "album_artist": "Artist",
         "isrc": "X"}])
    mock_playlist(api)
    mock_isrc(api, "X", [catalog_song("1", "Album", "Artist")])
    mock_equivalent(api, "1")
    mock_add(api, "1", status=500)

    cs.create_playlist_and_add_song(str(path))

    assert (tmp_path / "My playlist_noresult.txt").read_text() == (
        "Song | Artist | Album => UNABLE TO ADD TO PLAYLIST\n\n")
    assert "Converted Songs: 0\nFailed Songs: 1" in capsys.readouterr().out


def test_noresult_file_is_appended_across_runs(cs, api, tmp_path):
    (tmp_path / "My playlist_noresult.txt").write_text("Earlier | run | here => NOT FOUND\n\n")
    path = write_playlist_csv(tmp_path / "My_playlist.csv", [
        {"title": "Unknown", "artist": "Nobody", "album": "Nothing", "album_artist": "Nobody",
         "isrc": "X"}])
    mock_playlist(api)
    mock_not_found(api, "Unknown", "Nobody", "Nothing", "X")

    cs.create_playlist_and_add_song(str(path))

    assert (tmp_path / "My playlist_noresult.txt").read_text() == (
        "Earlier | run | here => NOT FOUND\n\nUnknown | Nobody | Nothing => NOT FOUND\n\n")


# __main__ ------------------------------------------------------------------------------

def test_main_converts_every_csv_file_of_a_directory(api, tmp_path, monkeypatch, capsys):
    write_credentials(tmp_path)
    playlists = tmp_path / "playlists"
    playlists.mkdir()
    write_playlist_csv(playlists / "First.csv", [])
    write_playlist_csv(playlists / "Second.csv", [])
    (playlists / "notes.txt").write_text("not a playlist")
    (playlists / "nested.csv").mkdir()  # not a file
    api.get(f"{AMP}/me/library/playlists", json={"data": []})
    created = []

    def create(request):
        created.append(json.loads(request.body)["attributes"]["name"])
        return 201, {}, json.dumps(apple("library_playlist_created.json"))

    api.add_callback(responses.POST, f"{AMP}/me/library/playlists", callback=create)
    api.get(f"{AMP}/me/library/playlists/p.NEWxPLtA75zg8/tracks", status=404)
    monkeypatch.setattr(sys, "argv", ["convertsongs.py", str(playlists)])
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    runpy.run_path(str(SCRIPT), run_name="__main__")

    assert sorted(created) == ["First", "Second"]
    assert capsys.readouterr().out.count("STAT REPORT") == 2
