# Spotify to Apple Music

Based on the work of [@simonschellaert](https://github.com/simonschellaert/spotify2am), [@therealmarius](https://github.com/therealmarius) and [@nf1973](https://github.com/nf1973)

### Import your Spotify playlist to Apple Music **for free** using Python!

## Usage

### 1. Export your Spotify Playlist to a CSV file

The first step is getting the songs you want to import into Apple Music into a CSV file. The simplest way to do this is to use [Exportify](https://watsonbox.github.io/exportify/).

You just need to login using your Spotify account, and all the playlists that you have saved in your library should appear. Export the CSV file of the playlist you want to convert and save it in the same directory as the directory where you cloned the repo.

If you build the CSV file another way, it must follow the format described in [CSV input format](#csv-input-format).

### 2. Match the Spotify songs with their Apple Music identifier and upload them to Apple Music

To upload your converted IDs to an Apple Music playlist, you'll need 5 things:

- The list of Apple Music identifiers (iTunes identifiers) for each song in your Spotify playlist
- Your Apple Music Authorization (Bearer Token)
- Your Apple Music Media-User-Token
- Your session cookies

Here's a step by step to get all of this data:

1. To get the list of Apple Music identifiers, all you got to do is get the file you downloaded from [Exportify](https://watsonbox.github.io/exportify/).
2. You can get all the other data using your favorite browser. Fire it up and open the [Apple Music web player](https://music.apple.com).
3. Open DevTools (**Ctrl + Shift + I or Cmd + Opt + I**) and go to the Network tab.
4. Then you'll need to log in to your account. If you're already logged in, please log out and log in again.
5. Go back to the DevTools and look for a GET request to *https://buy.music.apple.com/account/web/info* (It seems like there are 2 requests to this URL; it should be the second one).
6. In the **Requests Headers**, copy the **Authorization** (Please make sure to copy the `Bearer` part), the **Media-User-Token** and the **Cookies**.

   **ALL THIS DATA IS CASE SENSITIVE**. PLEASE MAKE SURE TO COPY IT RIGHT.

7. Install [uv](https://docs.astral.sh/uv/), which manages Python and the dependencies of this project. The uv version is pinned in `mise.toml`, so if you use [mise](https://mise.jdx.dev/) you can simply run:

```bash
mise install
```

(Without mise, [install uv](https://docs.astral.sh/uv/getting-started/installation/) yourself.)

8. Now you're finally ready to connvert your songs and push them onto your Apple Music playlist. To do so, open a terminal and run the following (on first run, `uv run` creates a `.venv` virtual environment and installs the dependencies automatically):

```bash
uv run convertsongs.py yourplaylist.csv
```

or

```bash
uv run convertsongs.py playlistdir
```

(Replace _yourplaylist.csv_ by your own filename, the one you got from [Exportify](https://watsonbox.github.io/exportify/), or _playlistdir_ by your own playlist directory name with all the `.csv` files you want to convert.)

Follow the script prompt, and when asked, paste in each data. If your terminal have a paste character limit: please hardcode them OR put them into separate files named as following: `token.dat`, `media_user_token.dat` and `cookies.dat`.

Please note that **the best practice** is to put your connection data as it can be reuse in a near future. Keep in mind that, those connection data will expire and you might need to get them again.

## CSV input format

`convertsongs.py` expects the CSV format produced by [Exportify](https://watsonbox.github.io/exportify/). Columns are read **by position**, not by name, so their order matters.

### File

- Comma-separated, with standard CSV quoting (double quotes around values containing commas, quotes or line breaks).
- Encoded in UTF-8.
- The first row is a header row; every other row is one track.
- Every row must have at least 17 columns (up to `ISRC`). Extra columns after it (such as Exportify's "Added By", "Added At", genres or audio features) are ignored.

### Columns

| # | Exportify header (English) | Used for | Header checked |
| --- | --- | --- | --- |
| 0 | Track URI | – | No |
| **1** | **Track Name** | Song title (text search) | Yes, see below |
| 2 | Artist URI(s) | – | No |
| **3** | **Artist Name(s)** | Artist (text search) | Yes, see below |
| 4 | Album URI | – | No |
| **5** | **Album Name** | Album (ISRC and text search) | Yes, see below |
| 6 | Album Artist URI(s) | – | No |
| **7** | **Album Artist Name(s)** | Album artist (ISRC search) | No |
| **8** | **Album Release Date** | Release date (text search) | No |
| 9 | Album Image URL | – | No |
| 10 | Disc Number | – | No |
| 11 | Track Number | – | No |
| 12 | Track Duration (ms) | – | No |
| 13 | Track Preview URL | – | No |
| 14 | Explicit | – | No |
| 15 | Popularity | – | No |
| **16** | **ISRC** | ISRC code (ISRC search) | Must be exactly `ISRC` |

Only the columns in bold are read; the others can be empty but must be present to keep the positions.

### Header check

Before converting anything, the script checks four header cells. If any of them doesn't match, it prints "The CSV file is not in the correct format!" and skips the file:

- Column 1 must be one of the "track name" headers listed in `csv_column_names.py`.
- Column 3 must be one of the "artist name" headers listed in `csv_column_names.py`.
- Column 5 must be one of the "album name" headers listed in `csv_column_names.py`.
- Column 16 must be exactly `ISRC`.

`csv_column_names.py` lists the headers Exportify uses in English, French, German, Spanish, Italian, Portuguese, Swedish, Turkish, Arabic and Japanese. Exportify headers in Greek and Dutch are currently rejected: Greek is missing from the list, and the Dutch track name is misspelled there (`Nummmernaam` instead of `Nummernaam`).

### Values

- **Artist names**: multiple artists are separated by `, ` (Exportify escapes commas inside a name as `\,`). The value is used as-is.
- **Album release date**: parsed with [dateparser](https://dateparser.readthedocs.io/), so any common format works. Spotify gives `YYYY-MM-DD`, `YYYY-MM` or `YYYY`.
- **ISRC**: can be empty; the track then falls back to the text search (title, artist and album).
- Apostrophes in every value are escaped (`'` becomes `\'`) before matching.

### Example

```csv
Track URI,Track Name,Artist URI(s),Artist Name(s),Album URI,Album Name,Album Artist URI(s),Album Artist Name(s),Album Release Date,Album Image URL,Disc Number,Track Number,Track Duration (ms),Track Preview URL,Explicit,Popularity,ISRC
,Morning Light - Remastered 2015,,The Lanterns,,Lantern Songs (Remastered),,The Lanterns,2000-11-13,,1,21,425653,,false,0,XXA011500001
```

### Playlist name and input path

- The Apple Music playlist is named after the CSV file: the file name up to its first `.`, with `_` replaced by spaces and only the first letter capitalized (`my_Road_Trip.csv` gives "My road trip"). The playlist is reused if it already exists.
- `uv run convertsongs.py <path>` treats `<path>` as a single file if it contains `.csv`, otherwise as a directory: every file in it (not in subdirectories) whose name contains `.csv` is converted, one playlist per file.

## Deezer API client

`deezer_api.py` is a small client for the public [Deezer API](https://api.deezer.com). `deezer2am.py` is the command line tool built on it: it lists your playlists and their tracks, and exports them to the CSV format of `convertsongs.py`. The client needs no authentication, so it can only read public data:

| Method | Endpoint | Returns |
| --- | --- | --- |
| `get_user_playlists(user_id=None, raw=False)` | `/user/{user_id}/playlists` | The user's **public** playlists |
| `get_playlist_tracks(playlist_id, raw=False)` | `/playlist/{id}/tracks` | All the tracks of a playlist, including their ISRC code |
| `get_track(track_id)` | `/track/{id}` | One track's details, including its ISRC code |

### Configuration

The client reads your Deezer user id from the `DEEZER_USER_ID` environment variable. Put it in a `.env` file at the root of the repository (this file is ignored by git):

```bash
DEEZER_USER_ID=<your_user_id>
```

Your user id is the number at the end of your Deezer profile URL (`https://www.deezer.com/profile/<your_user_id>`). Have uv load the file with `--env-file .env`.

### Command line usage

```bash
# List your public playlists: id, number of tracks, title
uv run --env-file .env deezer2am.py

# List a playlist's tracks: id, ISRC, artist - title
uv run --env-file .env deezer2am.py <playlist_id>
```

The output is logged to the console (stderr) with [loguru](https://github.com/Delgan/loguru). Set the `LOG_LEVEL` environment variable (`INFO` by default) to change its verbosity, e.g. `DEBUG` to see every request sent to the API:

```bash
LOG_LEVEL=DEBUG uv run --env-file .env deezer2am.py
```

#### JSON output

Add `--json` to print the JSON response of the API to stdout, for instance to analyze it with [jq](https://jqlang.org/). Paginated responses are merged: you get the first page's response with the `data` of all the following pages appended (and no `next` link), so it reads as one complete response. Since logs go to stderr, stdout only contains the JSON:

```bash
# Titles and number of tracks of your playlists
uv run --env-file .env deezer2am.py --json | jq -r '.data[] | "\(.nb_tracks)\t\(.title)"'

# ISRC, artist and title of a playlist's tracks
uv run --env-file .env deezer2am.py <playlist_id> --json | jq -r '.data[] | [.isrc, .artist.name, .title] | @tsv'
```

Add `2>/dev/null` to hide the logs as well.

#### CSV output

Add `--csv` to print a playlist's tracks to stdout in the [CSV input format](#csv-input-format) of `convertsongs.py`, so you can import a Deezer playlist into Apple Music:

```bash
uv run --env-file .env deezer2am.py <playlist_id> --csv > My_playlist.csv
uv run convertsongs.py My_playlist.csv
```

The URI columns hold Deezer links. The Deezer API gives no album artist, release date, disc number, track number or popularity for the tracks of a playlist: the track artist is used as the album artist and the other columns are left empty. Tracks are still matched by their ISRC code first.

`--csv` needs a playlist id and can't be combined with `--json`.

#### Converting a saved JSON response to CSV

Use `--from-json <file>` to convert a `get_playlist_tracks` JSON response you already have, such as the output of `--json`, to the same CSV format, without calling the API (so `DEEZER_USER_ID` isn't needed). Pass `-` to read the JSON from stdin; the playlist id is then required, to name the [missing data report](#missing-data-report):

```bash
uv run --env-file .env deezer2am.py <playlist_id> --json > My_playlist.json
uv run deezer2am.py --from-json My_playlist.json > My_playlist.csv

# Or edit the response with jq first, e.g. to keep the tracks with an ISRC code only
jq '.data |= map(select(.isrc))' My_playlist.json | uv run deezer2am.py <playlist_id> --from-json - > My_playlist.csv
```

The file must be a JSON object with a `data` list of tracks; a Deezer error response is reported as such. If it holds a single page of the playlist (it still has a `next` link, as when saved straight from the API), a warning is logged, since only that page's tracks are converted. With `--from-json`, a playlist id doesn't fetch anything: it only names the missing data report. `--from-json` can't be combined with `--json`.

#### Missing data report

`convertsongs.py` matches each track on its title, artist, album and ISRC code. When `--csv` or `--from-json` writes the CSV, the tracks where one of these is absent or empty are still written to the CSV (with an empty column), and also listed in a JSON report named after the playlist, `playlist-<playlist_id>-missing-data.json`. A warning gives its path and the number of tracks listed:

```text
10:12:55 | WARNING | 2 of 120 tracks miss data required by convertsongs.py, see playlist-1234567890-missing-data.json
```

The report is written to the current directory, or to the directory given with `--report-dir <dir>` (created if needed). With `--from-json` and no playlist id, the JSON file's name stands for it: `playlist-1234567890.json` gives `playlist-1234567890-missing-data.json`. When no track misses anything, no report is written, so an existing report from an earlier run is left as it is.

```json
{
  "playlist_id": "1234567890",
  "source": "Deezer API",
  "total_tracks": 120,
  "tracks_with_missing_data": 2,
  "tracks": [
    {
      "position": 4,
      "id": 900000101,
      "link": "https://www.deezer.com/track/900000101",
      "title": "Blue Hour",
      "artist": "Night Owls",
      "album": "Late Shows",
      "isrc": "",
      "missing": ["isrc"]
    },
    {
      "position": 6,
      "id": 900000102,
      "link": "https://www.deezer.com/track/900000102",
      "title": "Open Road",
      "artist": "Saltwater",
      "album": null,
      "isrc": "XXD011200001",
      "missing": ["album.title"]
    }
  ]
}
```

| Field | Content |
| --- | --- |
| `playlist_id` | The playlist id, or `null` with `--from-json` and no playlist id |
| `source` | `Deezer API`, or the file given to `--from-json` (`-` for stdin) |
| `total_tracks` | Number of tracks in the playlist |
| `tracks_with_missing_data` | Number of tracks listed in `tracks` |
| `tracks[].position` | Position of the track in the playlist (1 for the first), which is also its row in the CSV, header aside |
| `tracks[].id`, `link`, `title`, `artist`, `album`, `isrc` | What the Deezer API gives for the track (`null` when absent), to help you find it |
| `tracks[].missing` | The missing fields, as paths into the API track: `title`, `artist.name`, `album.title` and/or `isrc` |

A track without an ISRC code can't be matched by ISRC and falls back on the text search. A track missing its title, artist or album is unlikely to be found by the text search.

Reports match `*-missing-data.json` in `.gitignore`, like the CSV files.

### Python usage

```python
from deezer_api import DeezerApi, DeezerError

api = DeezerApi()  # or DeezerApi(user_id="<your_user_id>")

playlists = api.get_user_playlists()
for playlist in playlists:
    print(playlist["id"], playlist["title"])

tracks = api.get_playlist_tracks(playlists[0]["id"])
print(tracks[0]["isrc"], tracks[0]["artist"]["name"], tracks[0]["title"])

track = api.get_track(tracks[0]["id"])
print(track["isrc"], track["release_date"])
```

Notes:

- Paginated results are fetched in full by following Deezer's `next` links.
- With `raw=True`, `get_user_playlists` and `get_playlist_tracks` return the whole API response (all pages merged, as with `--json`) instead of the `data` list.
- The tracks returned by `get_playlist_tracks` already contain the ISRC code, so there is no need to call `get_track` for each one.
- Deezer reports errors with an HTTP 200 response holding an `error` object; the client raises them as `DeezerError` (with `type` and `code` attributes). HTTP failures raise `requests.HTTPError`.
- Deezer allows 50 requests per 5 seconds. When this quota is exceeded, the client waits 5 seconds and retries, up to `max_retries` times (3 by default).

### Running the tests

The tests mock the Deezer API with JSON responses stored in `tests/fixtures/`, so they don't need a network connection. `tests/test_deezer_api.py` tests the API client and `tests/test_deezer2am.py` the command line tool; their shared fixtures are in `tests/conftest.py` and helpers in `tests/helpers.py`:

```bash
uv run pytest
```

## Limitations & Notes

### iTunes StoreFront Region

Please note that the current script nneds to be configured with the iTunes StoreFront of **your Region**. Full list of ISO Code, provided by Wikipedia, [here](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2).

### Missing songs

The script to retrieve the Apple Music identifier for a Spotify song is quite basic. It simply compares the title, artist, and album name in many different combinations of search terms. The goal is to match an Apple Music song with your Spotify song and then get their iTunes identifier (it's the same as Apple Music identifiers). Some songs don't have the exact same title, artist, or album name (extraneous spacing, for example) in both services. This results in the script failing to retrieve an identifier for some songs. Hopefully, you'll be able to add the missing songs manually thanks to the **noresult.txt** file.

**UPDATE**: Starting with version 2.0 the script will now first try to match the ISRC of the songs, then (in case of failure of the first method) it will try to match the title, artist and album name. This should help with the matching of the songs and reduce the number of missing songs.

##### This repository is under the [Apache License 2.0](LICENSE)
