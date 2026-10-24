"""Command line interface to the public Deezer API (see deezer_api.py).

The user id is read from the DEEZER_USER_ID environment variable, e.g.:

    uv run --env-file .env deezer_client.py                # list playlists
    uv run --env-file .env deezer_client.py <playlist_id>  # list its tracks

Add --json to print the API JSON response to stdout, e.g. to pipe it to jq,
or --csv to print a playlist's tracks in the CSV format read by convertsongs.py.
Logs go to the console (stderr); set LOG_LEVEL (default: INFO) to DEBUG to see every request.
"""

import argparse
import csv
import json
import os
import sys

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


def track_to_csv_row(track):
    """Map a track of /playlist/{id}/tracks to a row of CSV_HEADER.

    Playlist tracks have no album artist, release date, disc or track number:
    the track artist stands for the album artist and the others are left empty.
    """
    artist, album = track["artist"], track["album"]
    # Exportify escapes the commas inside a name, as it separates artists with ", "
    artist_name = artist["name"].replace(",", "\\,")
    return [
        track.get("link", ""), track["title"], artist.get("link", ""), artist_name,
        f"https://www.deezer.com/album/{album['id']}", album["title"],
        artist.get("link", ""), artist_name, "", album.get("cover_xl", ""),
        "", "", track["duration"] * 1000, track.get("preview", ""),
        str(track.get("explicit_lyrics", False)).lower(), "", track.get("isrc", ""),
    ]


def write_csv(tracks, out):
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerows(track_to_csv_row(track) for track in tracks)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="List the public playlists of DEEZER_USER_ID, or the tracks of a playlist.")
    parser.add_argument("playlist_id", nargs="?",
                        help="list the tracks of this playlist instead of the playlists")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true",
                        help="print the API JSON response to stdout (all pages merged), "
                             "e.g. to pipe it to jq")
    output.add_argument("--csv", action="store_true",
                        help="print the playlist's tracks to stdout in the CSV format "
                             "read by convertsongs.py")
    args = parser.parse_args(argv)
    if args.csv and not args.playlist_id:
        parser.error("--csv requires a playlist_id")
    return args


def main(argv=None):
    args = parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("LOG_LEVEL", "INFO"),
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")

    api = DeezerApi()
    try:
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
    except (DeezerError, ValueError, requests.RequestException) as error:
        logger.error(error)
        sys.exit(1)


if __name__ == "__main__":
    main()
