"""Export Deezer playlists to the CSV format read by convertsongs.py.

Lists public playlists and their tracks with the Deezer API (see deezer_api.py),
and converts them, or a saved API response, to CSV.

The user id is read from the DEEZER_USER_ID environment variable, e.g.:

    uv run --env-file .env deezer2am.py                # list playlists
    uv run --env-file .env deezer2am.py <playlist_id>  # list its tracks

Add --json to print the API JSON response to stdout, e.g. to pipe it to jq,
or --csv to print a playlist's tracks in the CSV format read by convertsongs.py.
Use --from-json FILE to convert a saved get_playlist_tracks response (e.g. the
output of --json) to that CSV format without calling the API:

    uv run deezer2am.py --from-json playlist.json > playlist.csv

When writing CSV, tracks that miss data required by convertsongs.py are listed
in a JSON report, playlist-<playlist_id>-missing-data.json (see --report-dir).
Logs go to the console (stderr); set LOG_LEVEL (default: INFO) to DEBUG to see every request.
"""

import argparse
import csv
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path

import requests
from loguru import logger

from deezer_api import DeezerApi, DeezerError

# Exportify's columns, in the order convertsongs.py reads them (see "CSV input format" in README.md)
CSV_HEADER = [
    "Track URI", "Track Name", "Artist URI(s)", "Artist Name(s)", "Album URI", "Album Name",
    "Album Artist URI(s)", "Album Artist Name(s)", "Album Release Date", "Album Image URL",
    "Disc Number", "Track Number", "Track Duration (ms)", "Track Preview URL", "Explicit",
    "Popularity", "ISRC",
]

# Track fields convertsongs.py matches on (dotted paths into the API track), see missing_fields()
REQUIRED_FIELDS = ["title", "artist.name", "album.title", "isrc"]


def track_to_csv_row(track):
    """Map a track of /playlist/{id}/tracks to a row of CSV_HEADER.

    Playlist tracks have no album artist, release date, disc or track number:
    the track artist stands for the album artist and the others are left empty.
    Missing fields are left empty too (see missing_fields()).
    """
    artist, album = track.get("artist") or {}, track.get("album") or {}
    # Exportify escapes the commas inside a name, as it separates artists with ", "
    artist_name = (artist.get("name") or "").replace(",", "\\,")
    album_uri = f"https://www.deezer.com/album/{album['id']}" if album.get("id") else ""
    duration = track.get("duration")
    return [
        track.get("link", ""), track.get("title") or "", artist.get("link", ""), artist_name,
        album_uri, album.get("title") or "",
        artist.get("link", ""), artist_name, "", album.get("cover_xl", ""),
        "", "", duration * 1000 if isinstance(duration, int) else "", track.get("preview", ""),
        str(track.get("explicit_lyrics", False)).lower(), "", track.get("isrc", ""),
    ]


def write_csv(tracks, out):
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerows(track_to_csv_row(track) for track in tracks)


def missing_fields(track):
    """Return the REQUIRED_FIELDS that are absent or empty in a track."""
    missing = []
    for field in REQUIRED_FIELDS:
        value = track
        for key in field.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def missing_data_report(tracks, playlist_id, source):
    """Return the report of the tracks missing REQUIRED_FIELDS, or None if none miss any.

    "position" is the track's 1-based position in the playlist, i.e. its CSV row
    (the header aside).
    """
    entries = []
    for position, track in enumerate(tracks, 1):
        if missing := missing_fields(track):
            artist, album = track.get("artist") or {}, track.get("album") or {}
            entries.append({
                "position": position, "id": track.get("id"), "link": track.get("link"),
                "title": track.get("title"), "artist": artist.get("name"),
                "album": album.get("title"), "isrc": track.get("isrc"), "missing": missing,
            })
    if not entries:
        return None
    return {"playlist_id": playlist_id, "source": source, "total_tracks": len(tracks),
            "tracks_with_missing_data": len(entries), "tracks": entries}


def write_missing_data_report(tracks, playlist_id, source, path):
    """Write the missing data report of tracks to path; return path, or None if nothing misses."""
    report = missing_data_report(tracks, playlist_id, source)
    if report is None:
        logger.info("All {} tracks have the data required by convertsongs.py", len(tracks))
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.warning("{} of {} tracks miss data required by convertsongs.py, see {}",
                   report["tracks_with_missing_data"], len(tracks), path)
    return path


def report_path(args):
    """playlist-<playlist_id>-missing-data.json in --report-dir.

    With --from-json and no playlist_id, the JSON file's name stands for it:
    playlist-123.json gives playlist-123-missing-data.json.
    """
    name = f"playlist-{args.playlist_id}" if args.playlist_id else Path(args.from_json).stem
    return Path(args.report_dir) / f"{name}-missing-data.json"


def load_playlist_tracks(path):
    """Return the tracks of a get_playlist_tracks JSON response read from path ("-" for stdin)."""
    with nullcontext(sys.stdin) if path == "-" else open(path, encoding="utf-8") as file:
        response = json.load(file)
    if isinstance(response, dict) and response.get("error"):
        raise DeezerError(response["error"])
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        raise ValueError(f'{path} is not a get_playlist_tracks response: no "data" list')
    if response.get("next"):
        logger.warning("{} is a single page of the playlist ({} of {} tracks): use --json "
                       "to save all its pages", path, len(response["data"]),
                       response.get("total", "?"))
    return response["data"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="List the public playlists of DEEZER_USER_ID, or the tracks of a playlist.")
    parser.add_argument("playlist_id", nargs="?",
                        help="list the tracks of this playlist instead of the playlists; "
                             "with --from-json, only names the missing data report")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true",
                        help="print the API JSON response to stdout (all pages merged), "
                             "e.g. to pipe it to jq")
    output.add_argument("--csv", action="store_true",
                        help="print the playlist's tracks to stdout in the CSV format "
                             "read by convertsongs.py")
    output.add_argument("--from-json", metavar="FILE",
                        help="print the tracks of FILE, a get_playlist_tracks JSON response "
                             "(e.g. saved with --json), to stdout in the CSV format read by "
                             "convertsongs.py, without calling the API; - reads stdin")
    parser.add_argument("--report-dir", default=".", metavar="DIR",
                        help="with --csv or --from-json, write the report of the tracks "
                             "missing data required by convertsongs.py, "
                             "playlist-<playlist_id>-missing-data.json, to DIR "
                             "(default: current directory)")
    args = parser.parse_args(argv)
    if args.from_json == "-" and not args.playlist_id:
        parser.error("--from-json - requires a playlist_id to name the missing data report")
    if args.csv and not args.playlist_id:
        parser.error("--csv requires a playlist_id")
    return args


def main(argv=None):
    args = parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("LOG_LEVEL", "INFO"),
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")

    try:
        if args.from_json:
            tracks = load_playlist_tracks(args.from_json)
            logger.info("{} has {} tracks", args.from_json, len(tracks))
            write_csv(tracks, sys.stdout)
            write_missing_data_report(tracks, args.playlist_id, args.from_json, report_path(args))
            return
        api = DeezerApi()
        if args.playlist_id:
            response = api.get_playlist_tracks(args.playlist_id, raw=True)
            tracks = response.get("data", [])
            logger.info("Playlist {} has {} tracks", args.playlist_id, len(tracks))
            if not (args.json or args.csv):
                for track in tracks:
                    logger.info("{}\t{}\t{} - {}", track["id"], track.get("isrc", ""),
                                track["artist"]["name"], track["title"])
        else:
            response = api.get_user_playlists(raw=True)
            playlists = response.get("data", [])
            logger.info("User {} has {} public playlists", api.user_id, len(playlists))
            if not args.json:
                for playlist in playlists:
                    logger.info("{}\t{} tracks\t{}", playlist["id"], playlist["nb_tracks"],
                                playlist["title"])
        if args.json:
            # Data output, not logging: stdout stays pure JSON while logs go to stderr
            json.dump(response, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        elif args.csv:
            write_csv(tracks, sys.stdout)
            write_missing_data_report(tracks, args.playlist_id, "Deezer API", report_path(args))
    except (DeezerError, ValueError, OSError, requests.RequestException) as error:
        logger.error(error)
        sys.exit(1)


if __name__ == "__main__":
    main()
